from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class WorkoutSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20))
    muscle = db.Column(db.String(50))

    exercises = db.relationship('ExerciseLog', backref='session')


class Exercise(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)


class ExerciseLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('workout_session.id'))
    exercise_id = db.Column(db.Integer, db.ForeignKey('exercise.id'))

    exercise = db.relationship('Exercise')


class SetLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exercise_log_id = db.Column(db.Integer, db.ForeignKey('exercise_log.id'))
    set_number = db.Column(db.Integer)
    weight = db.Column(db.Float)
    reps = db.Column(db.Integer)

    exercise_log = db.relationship('ExerciseLog')