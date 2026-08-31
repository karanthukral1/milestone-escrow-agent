import os
from datetime import datetime

from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.models import Project, Milestone, AuditEvent, MilestoneStatus, SessionLocal, init_db
from app import razorpay_client
from app import ai_review

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Milestone Escrow Agent")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

init_db()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def log_event(db: Session, milestone: Milestone, actor: str, action: str,
              detail: str = "", from_status=None, to_status=None):
    ev = AuditEvent(
        milestone_id=milestone.id,
        actor=actor,
        action=action,
        detail=detail,
        from_status=from_status.value if from_status else None,
        to_status=to_status.value if to_status else None,
    )
    db.add(ev)


# ---------------------------------------------------------------- listing --

@app.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return templates.TemplateResponse(
        request,
        "home.html",
        {"projects": projects, "mock_mode": razorpay_client.is_mock_mode()},
    )


@app.get("/projects/new")
def new_project_form(request: Request):
    return templates.TemplateResponse(request, "new_project.html", {})


@app.post("/projects")
def create_project(
    title: str = Form(...),
    client_name: str = Form(...),
    freelancer_name: str = Form(...),
    db: Session = Depends(get_db),
):
    project = Project(title=title, client_name=client_name, freelancer_name=freelancer_name)
    db.add(project)
    db.commit()
    db.refresh(project)
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


# ---------------------------------------------------------------- project --

@app.get("/projects/{project_id}")
def project_detail(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).get(project_id)
    return templates.TemplateResponse(
        request,
        "project.html",
        {"project": project, "mock_mode": razorpay_client.is_mock_mode()},
    )


@app.post("/projects/{project_id}/milestones")
def add_milestone(
    project_id: int,
    title: str = Form(...),
    scope_description: str = Form(...),
    amount_inr: float = Form(...),
    db: Session = Depends(get_db),
):
    m = Milestone(
        project_id=project_id,
        title=title,
        scope_description=scope_description,
        amount_inr=amount_inr,
        status=MilestoneStatus.PENDING_FUNDING,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    log_event(db, m, "client", "milestone_created", f"Amount: Rs.{amount_inr}",
              to_status=MilestoneStatus.PENDING_FUNDING)
    db.commit()
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


# -------------------------------------------------------------- milestone --

@app.post("/milestones/{milestone_id}/fund")
def fund_milestone(milestone_id: int, db: Session = Depends(get_db)):
    m = db.query(Milestone).get(milestone_id)
    if m is None:
        return RedirectResponse("/", status_code=303)

    # --- idempotency guard ---
    # This is an atomic UPDATE...WHERE, not a read-then-write check. Two
    # simultaneous "Fund Milestone" clicks (double-click, retried request,
    # whatever) both pass the read-only check above, but only ONE of them
    # can win this atomic claim -- the other gets rowcount=0 and bails out
    # BEFORE any Razorpay order is created. Without this, a race could
    # create two orders for the same milestone and silently drop the first
    # order_id when the second write lands.
    claimed = (
        db.query(Milestone)
        .filter(Milestone.id == milestone_id, Milestone.status == MilestoneStatus.PENDING_FUNDING)
        .update({"status": MilestoneStatus.FUNDED, "updated_at": datetime.utcnow()})
    )
    db.commit()

    if claimed == 0:
        # Someone else already funded this milestone (or it was never in
        # PENDING_FUNDING to begin with) -- no order created, no duplicate.
        return RedirectResponse(f"/projects/{m.project_id}", status_code=303)

    db.refresh(m)
    order = razorpay_client.create_hold_order(
        amount_inr=m.amount_inr,
        receipt=f"milestone_{m.id}",
        notes={"milestone_title": m.title, "project_id": str(m.project_id)},
    )
    m.razorpay_order_id = order["id"]
    log_event(
        db, m, "client", "milestone_funded",
        f"Razorpay order {order['id']} (mock={order.get('mock')})",
        from_status=MilestoneStatus.PENDING_FUNDING, to_status=MilestoneStatus.FUNDED,
    )
    db.commit()
    return RedirectResponse(f"/projects/{m.project_id}", status_code=303)


@app.post("/milestones/{milestone_id}/deliver")
def deliver_milestone(
    milestone_id: int,
    deliverable_link: str = Form(""),
    deliverable_note: str = Form(""),
    db: Session = Depends(get_db),
):
    m = db.query(Milestone).get(milestone_id)
    # Allow this route from FUNDED (first submission) or DISPUTED (freelancer
    # fixing a disputed deliverable and resubmitting).
    if m.status not in (MilestoneStatus.FUNDED, MilestoneStatus.DISPUTED):
        return RedirectResponse(f"/projects/{m.project_id}", status_code=303)

    # --- validation: reject empty/whitespace-only submissions before they
    # ever reach the AI layer, rather than letting the AI "discover" that
    # the submission is empty via a flag. Fail fast, fail cheap. ---
    link_clean = (deliverable_link or "").strip()
    note_clean = (deliverable_note or "").strip()
    if len(link_clean) < 4 or len(note_clean) < 3:
        log_event(
            db, m, "freelancer", "deliverable_rejected_at_route",
            "Submission rejected: link or note too short/empty to process",
        )
        db.commit()
        return RedirectResponse(f"/projects/{m.project_id}", status_code=303)

    is_resubmission = m.status == MilestoneStatus.DISPUTED
    m.deliverable_link = deliverable_link
    m.deliverable_note = deliverable_note

    old_status = m.status
    log_event(
        db, m, "freelancer",
        "deliverable_resubmitted" if is_resubmission else "deliverable_submitted",
        f"link={deliverable_link!r}", from_status=old_status,
    )

    # --- AI review step (advisory only) ---
    review = ai_review.review_deliverable(m.scope_description, deliverable_link, deliverable_note)
    m.ai_summary = review["summary"]
    m.ai_recommendation = review["recommendation"]
    m.ai_flags = ", ".join(review["flags"]) if review["flags"] else ""

    m.status = MilestoneStatus.FLAGGED if review["flags"] else MilestoneStatus.DELIVERED
    m.updated_at = datetime.utcnow()

    log_event(
        db, m, "ai", "ai_review_complete",
        f"recommendation={review['recommendation']}, flags={review['flags']}",
        from_status=old_status, to_status=m.status,
    )
    db.commit()
    return RedirectResponse(f"/projects/{m.project_id}", status_code=303)


@app.post("/milestones/{milestone_id}/release")
def release_milestone(milestone_id: int, db: Session = Depends(get_db)):
    """Human-only action. Can be triggered from DELIVERED, FLAGGED, or DISPUTED
    (client can still choose to release after a dispute is resolved off-platform)."""
    m = db.query(Milestone).get(milestone_id)
    if m.status not in (MilestoneStatus.DELIVERED, MilestoneStatus.FLAGGED, MilestoneStatus.DISPUTED):
        return RedirectResponse(f"/projects/{m.project_id}", status_code=303)

    result = razorpay_client.release_payment(m.razorpay_order_id, m.razorpay_payment_id)
    old_status = m.status
    m.status = MilestoneStatus.RELEASED
    m.updated_at = datetime.utcnow()
    log_event(
        db, m, "client", "payment_released",
        f"Razorpay release {result['id']} (mock={result.get('mock')})",
        from_status=old_status, to_status=m.status,
    )
    db.commit()
    return RedirectResponse(f"/projects/{m.project_id}", status_code=303)


@app.post("/milestones/{milestone_id}/dispute")
def dispute_milestone(milestone_id: int, reason: str = Form(""), db: Session = Depends(get_db)):
    m = db.query(Milestone).get(milestone_id)
    if m.status not in (MilestoneStatus.DELIVERED, MilestoneStatus.FLAGGED):
        return RedirectResponse(f"/projects/{m.project_id}", status_code=303)

    old_status = m.status
    m.status = MilestoneStatus.DISPUTED
    m.updated_at = datetime.utcnow()
    log_event(db, m, "client", "milestone_disputed", reason,
              from_status=old_status, to_status=m.status)
    db.commit()
    return RedirectResponse(f"/projects/{m.project_id}", status_code=303)


@app.post("/milestones/{milestone_id}/refund")
def refund_milestone(milestone_id: int, db: Session = Depends(get_db)):
    m = db.query(Milestone).get(milestone_id)
    if m.status != MilestoneStatus.DISPUTED:
        return RedirectResponse(f"/projects/{m.project_id}", status_code=303)

    old_status = m.status
    m.status = MilestoneStatus.REFUNDED
    m.updated_at = datetime.utcnow()
    log_event(db, m, "client", "milestone_refunded", "Refunded to client after dispute",
              from_status=old_status, to_status=m.status)
    db.commit()
    return RedirectResponse(f"/projects/{m.project_id}", status_code=303)
