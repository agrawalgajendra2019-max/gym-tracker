import socket

def force_ipv4():
    orig_getaddrinfo = socket.getaddrinfo

    def new_getaddrinfo(*args, **kwargs):
        return [res for res in orig_getaddrinfo(*args, **kwargs) if res[0] == socket.AF_INET]

    socket.getaddrinfo = new_getaddrinfo

force_ipv4()


from flask import Flask, render_template, request, redirect, url_for, Response
from models import db, WorkoutSession, Exercise, ExerciseLog, SetLog

from services.progression import is_pr
from services.analytics import (
    calculate_total_volume,
    get_previous_weight,
    calculate_improvement
)

app = Flask(__name__)

import os

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://")

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL or 'sqlite:///gym.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
}

db.init_app(app)

try:
    with app.app_context():
        print("CREATING TABLES...")
        db.create_all()
        print("TABLES CREATED")
except Exception as e:
    print("DB INIT ERROR:", e)

# -------------------------
# STEP 1: ADD WORKOUT
# -------------------------
@app.route('/', methods=['GET', 'POST'])
def add_workout():

    if request.method == 'POST':
        date = request.form['date']
        muscle = request.form['muscle'].strip().lower()

        session = WorkoutSession(date=date, muscle=muscle)
        db.session.add(session)
        db.session.commit()

        return redirect(url_for('add_exercise', session_id=session.id))

    print("---- DEBUG ----")
    sessions = WorkoutSession.query.order_by(WorkoutSession.id).all()
    print("ALL MUSCLES:", [s.muscle for s in sessions])

    cycle, last_muscle, next_muscle = get_cycle_status()

    print("CYCLE:", cycle)
    print("LAST:", last_muscle)
    print("NEXT:", next_muscle)
    print("----------------")

    return render_template(
        'add_workout.html',
        cycle=cycle,
        last_muscle=last_muscle,
        suggested_muscle=next_muscle
    )


# -------------------------
# STEP 2: ADD EXERCISE
# -------------------------
@app.route('/add_exercise/<int:session_id>', methods=['GET', 'POST'])
def add_exercise(session_id):
    session = WorkoutSession.query.get(session_id)

    logs = ExerciseLog.query.filter_by(session_id=session_id).all()

    used_exercise_ids = [l.exercise_id for l in logs]

    exercises = Exercise.query.filter(~Exercise.id.in_(used_exercise_ids)).all()

    if request.method == 'POST':
        existing = request.form.get('existing_exercise')
        new = request.form.get('new_exercise')

        if existing:
            name = existing.strip().lower()
        elif new:
            name = new.strip().lower()
        else:
            return "Please select or enter an exercise"

        exercise = Exercise.query.filter(Exercise.name.ilike(name)).first()

        if not exercise:
            exercise = Exercise(name=name)
            db.session.add(exercise)
            db.session.commit()

        log = ExerciseLog(session_id=session_id, exercise_id=exercise.id)
        db.session.add(log)
        db.session.commit()

        return redirect(url_for('add_sets', log_id=log.id))

    return render_template(
        'add_exercise.html',
        exercises=exercises,
        muscle=session.muscle,
        logs=logs
    )


@app.route('/add_sets/<int:log_id>', methods=['GET', 'POST'])
def add_sets(log_id):
    if request.method == 'POST':
        sets = int(request.form['sets'])

        for i in range(1, sets + 1):
            weight = request.form.get(f'weight_{i}')
            reps = request.form.get(f'reps_{i}')

            if not weight or not reps:
                continue

            set_entry = SetLog(
                exercise_log_id=log_id,
                set_number=i,
                weight=float(weight),
                reps=int(reps)
            )

            db.session.add(set_entry)

        db.session.commit()

        return redirect(url_for('add_exercise', session_id=ExerciseLog.query.get(log_id).session_id))

    return render_template('add_sets.html', log_id=log_id)


# -------------------------
# CYCLE LOGIC
# -------------------------
def detect_cycle():
    sessions = WorkoutSession.query.order_by(WorkoutSession.id).all()

    sequence = []

    for s in sessions:
        muscle = s.muscle.strip().lower()

        if sequence and muscle == sequence[-1]:
            continue

        if sequence and muscle == sequence[0] and len(sequence) >= 3:
            return sequence

        if muscle not in sequence:
            sequence.append(muscle)

    return None


def get_cycle_status():
    cycle = detect_cycle()

    if not cycle:
        return None, None, None

    last_session = WorkoutSession.query.order_by(WorkoutSession.id.desc()).first()
    last_muscle = last_session.muscle.strip().lower()

    if last_muscle in cycle:
        index = cycle.index(last_muscle)
        next_index = (index + 1) % len(cycle)

        return cycle, last_muscle, cycle[next_index]

    return cycle, None, cycle[0]


# -------------------------
# DASHBOARD (FIXED)
# -------------------------
@app.route('/dashboard')
def dashboard():

    muscle = request.args.get('muscle')
    exercise = request.args.get('exercise')
    date = request.args.get('date')

    # 🔥 IMPORTANT: join ALL tables properly
    query = SetLog.query \
        .join(ExerciseLog) \
        .join(WorkoutSession) \
        .join(Exercise)

    # 🔥 SAFE FILTERS
    if muscle:
        query = query.filter(WorkoutSession.muscle.ilike(f"%{muscle}%"))

    if exercise:
        query = query.filter(Exercise.name.ilike(f"%{exercise}%"))

    if date:
        query = query.filter(WorkoutSession.date == date)

    logs = query.all()
    all_logs = SetLog.query.all()

    print("FILTERED LOGS:", len(logs))

    total_volume = calculate_total_volume(logs)
    total_sets = len(logs)

    # 🔥 FINAL DATA (PR + IMPROVEMENT)
    logs_with_data = []

    for log in logs:
        try:
            pr_flag = is_pr(log, all_logs)

            prev_weight = get_previous_weight(log, all_logs)
            improvement = calculate_improvement(log.weight, prev_weight)

        except Exception as e:
            print("ERROR:", e)
            pr_flag = False
            improvement = None

        logs_with_data.append((log, pr_flag, improvement))

    print("FINAL LOGS:", len(logs_with_data))

    return render_template(
        'dashboard.html',
        logs=logs_with_data,
        total_volume=total_volume,
        total_sets=total_sets
    )



import csv
from flask import Response

@app.route('/export_csv')
def export_csv():

    muscle = request.args.get('muscle')
    exercise = request.args.get('exercise')
    date = request.args.get('date')

    query = SetLog.query \
        .join(ExerciseLog) \
        .join(WorkoutSession) \
        .join(Exercise)

    if muscle and muscle.strip():
        query = query.filter(WorkoutSession.muscle.ilike(f"%{muscle}%"))

    if exercise and exercise.strip():
        query = query.filter(Exercise.name.ilike(f"%{exercise}%"))

    if date and date.strip():
        query = query.filter(WorkoutSession.date == date)

    logs = query.all()

    print("EXPORT LOGS:", len(logs))

    # 🔥 EXTRACT DATA FIRST (IMPORTANT FIX)
    data_rows = []

    for log in logs:
        data_rows.append([
            log.exercise_log.session.date,
            log.exercise_log.session.muscle,
            log.exercise_log.exercise.name,
            log.weight,
            log.reps
        ])

    # 🔥 NOW GENERATE CSV (NO DB ACCESS HERE)
    def generate():
        yield 'Date,Muscle,Exercise,Weight,Reps\n'

        for row in data_rows:
            yield f"{row[0]},{row[1]},{row[2]},{row[3]},{row[4]}\n"

    return Response(
        generate(),
        mimetype='text/csv',
        headers={"Content-Disposition": "attachment;filename=workout_data.csv"}
    )

# -------------------------
# RUN
# -------------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5001)