import os
from typing import Dict, List

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Integer, Boolean, JSON, UniqueConstraint
from sqlalchemy.orm import sessionmaker, declarative_base, Session

# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------
# Locally this defaults to a SQLite file (no setup needed).
# In production, set the DATABASE_URL environment variable to your Postgres
# connection string (e.g. from Neon.tech) — see README.md for how.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./edutrack.db")

# Render/Neon sometimes give a URL starting with postgres:// — SQLAlchemy
# needs postgresql:// instead.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


# ---------------------------------------------------------------------------
# Database tables (SQLAlchemy models)
# ---------------------------------------------------------------------------
class SubjectRow(Base):
    __tablename__ = "subjects"
    name = Column(String, primary_key=True)


class StudentRow(Base):
    __tablename__ = "students"
    id = Column(String, primary_key=True)
    password = Column(String, nullable=False)
    name = Column(String, nullable=False)
    class_name = Column(String, nullable=False)


class AdminRow(Base):
    __tablename__ = "admins"
    id = Column(String, primary_key=True)
    password = Column(String, nullable=False)
    name = Column(String, nullable=False)


class ExamRow(Base):
    __tablename__ = "exams"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    date = Column(String, nullable=False)  # stored as ISO date string, e.g. "2026-07-14"
    subjects = Column(JSON, nullable=False, default=list)
    max_marks = Column(JSON, nullable=False, default=dict)          # {subject: maxMarks}
    results = Column(JSON, nullable=False, default=dict)            # {studentId: {subject: mark}}


class AttendanceRow(Base):
    __tablename__ = "attendance"
    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String, nullable=False)
    date = Column(String, nullable=False)  # ISO date string
    present = Column(Boolean, nullable=False)
    __table_args__ = (UniqueConstraint("student_id", "date", name="uix_student_date"),)


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def seed_if_empty(db: Session):
    """Adds sample data on first run, so the API isn't empty."""
    if db.query(AdminRow).count() == 0:
        db.add(AdminRow(id="admin", password="admin123", name="Principal Rao"))
    if db.query(SubjectRow).count() == 0:
        for s in ["Mathematics", "Science", "English", "Social Studies"]:
            db.add(SubjectRow(name=s))
    if db.query(StudentRow).count() == 0:
        for sid, pw, name in [
            ("STU101", "pass101", "Aarav Sharma"),
            ("STU102", "pass102", "Diya Patel"),
            ("STU103", "pass103", "Ishaan Kumar"),
        ]:
            db.add(StudentRow(id=sid, password=pw, name=name, class_name="10th Grade - A"))
    db.commit()


with SessionLocal() as _db:
    seed_if_empty(_db)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="EduTrack API")

# Allow the Flutter web app (running on any domain) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request/response schemas
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    id: str
    password: str


class StudentIn(BaseModel):
    id: str
    password: str
    name: str
    className: str


class SubjectIn(BaseModel):
    name: str


class ExamIn(BaseModel):
    id: str
    name: str
    date: str
    subjects: List[str]
    maxMarks: Dict[str, int]


class ResultsIn(BaseModel):
    studentId: str
    marks: Dict[str, int]


class AttendanceIn(BaseModel):
    studentId: str
    date: str
    present: bool


def student_to_dict(s: StudentRow):
    return {"id": s.id, "password": s.password, "name": s.name, "className": s.class_name}


def exam_to_dict(e: ExamRow):
    return {
        "id": e.id,
        "name": e.name,
        "date": e.date,
        "subjects": e.subjects,
        "maxMarks": e.max_marks,
        "results": e.results,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    return {"status": "EduTrack API is running"}


@app.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    admin = db.query(AdminRow).filter_by(id=req.id, password=req.password).first()
    if admin:
        return {"role": "admin"}
    student = db.query(StudentRow).filter_by(id=req.id, password=req.password).first()
    if student:
        return {"role": "student", "student": student_to_dict(student)}
    raise HTTPException(status_code=401, detail="Invalid ID or password")


@app.get("/subjects")
def get_subjects(db: Session = Depends(get_db)):
    return [s.name for s in db.query(SubjectRow).all()]


@app.post("/subjects")
def add_subject(body: SubjectIn, db: Session = Depends(get_db)):
    if not db.query(SubjectRow).filter_by(name=body.name).first():
        db.add(SubjectRow(name=body.name))
        db.commit()
    return {"ok": True}


@app.delete("/subjects/{name}")
def remove_subject(name: str, db: Session = Depends(get_db)):
    row = db.query(SubjectRow).filter_by(name=name).first()
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}


@app.get("/students")
def get_students(db: Session = Depends(get_db)):
    return [student_to_dict(s) for s in db.query(StudentRow).all()]


@app.post("/students")
def add_student(body: StudentIn, db: Session = Depends(get_db)):
    if db.query(StudentRow).filter_by(id=body.id).first():
        raise HTTPException(status_code=400, detail="Student ID already exists")
    db.add(StudentRow(id=body.id, password=body.password, name=body.name, class_name=body.className))
    db.commit()
    return {"ok": True}


@app.delete("/students/{student_id}")
def remove_student(student_id: str, db: Session = Depends(get_db)):
    row = db.query(StudentRow).filter_by(id=student_id).first()
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}


@app.get("/exams")
def get_exams(db: Session = Depends(get_db)):
    return [exam_to_dict(e) for e in db.query(ExamRow).all()]


@app.post("/exams")
def add_exam(body: ExamIn, db: Session = Depends(get_db)):
    db.add(ExamRow(
        id=body.id, name=body.name, date=body.date,
        subjects=body.subjects, max_marks=body.maxMarks, results={},
    ))
    db.commit()
    return {"ok": True}


@app.delete("/exams/{exam_id}")
def remove_exam(exam_id: str, db: Session = Depends(get_db)):
    row = db.query(ExamRow).filter_by(id=exam_id).first()
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}


@app.post("/exams/{exam_id}/results")
def submit_results(exam_id: str, body: ResultsIn, db: Session = Depends(get_db)):
    exam = db.query(ExamRow).filter_by(id=exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    results = dict(exam.results or {})
    results[body.studentId] = body.marks
    exam.results = results
    db.commit()
    return {"ok": True}


@app.get("/attendance")
def get_attendance(db: Session = Depends(get_db)):
    return [
        {"studentId": a.student_id, "date": a.date, "present": a.present}
        for a in db.query(AttendanceRow).all()
    ]


@app.post("/attendance")
def set_attendance(body: AttendanceIn, db: Session = Depends(get_db)):
    row = db.query(AttendanceRow).filter_by(student_id=body.studentId, date=body.date).first()
    if row:
        row.present = body.present
    else:
        db.add(AttendanceRow(student_id=body.studentId, date=body.date, present=body.present))
    db.commit()
    return {"ok": True}
