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
import csv
from io import TextIOWrapper


STANDARD_EXERCISES = {

    "chest": [
        "bench press", "incline bench press", "decline bench press",
        "dumbbell bench press", "incline dumbbell press",
        "chest fly", "cable crossover", "pec deck",
        "push up", "incline push up", "decline push up",
        "machine chest press", "smith machine bench press",
        "single arm cable fly", "floor press"
    ],

    "back": [
        "pull up", "chin up", "lat pulldown", "wide grip pulldown",
        "barbell row", "dumbbell row", "t-bar row",
        "seated cable row", "machine row",
        "deadlift", "rack pull", "straight arm pulldown",
        "reverse fly", "face pull"
    ],

    "shoulder": [
        "overhead press", "dumbbell shoulder press",
        "arnold press", "machine shoulder press",
        "lateral raise", "cable lateral raise",
        "front raise", "plate raise",
        "rear delt fly", "reverse pec deck",
        "face pull", "upright row"
    ],

    "biceps": [
        "barbell curl", "ez bar curl", "dumbbell curl",
        "alternating curl", "hammer curl",
        "incline dumbbell curl", "concentration curl",
        "preacher curl", "cable curl",
        "reverse curl", "spider curl"
    ],

    "triceps": [
        "tricep pushdown", "rope pushdown",
        "overhead extension", "dumbbell overhead extension",
        "skull crusher", "lying tricep extension",
        "close grip bench press", "dips",
        "bench dips", "kickbacks", "cable overhead extension"
    ],

    "legs": [
        "squat", "front squat", "goblet squat",
        "leg press", "hack squat",
        "lunges", "walking lunges", "bulgarian split squat",
        "leg curl", "lying leg curl", "seated leg curl",
        "leg extension",
        "romanian deadlift", "stiff leg deadlift",
        "calf raise", "seated calf raise", "standing calf raise"
    ]
}


app = Flask(__name__)

import os

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://")

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL or 'sqlite:///gym.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

print("DB:", app.config['SQLALCHEMY_DATABASE_URI'])

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

    # 🔥 RECENT EXERCISES (last 10 used)
    recent_logs = ExerciseLog.query.order_by(ExerciseLog.id.desc()).limit(10).all()
    recent_names = []

    for log in recent_logs:
        name = log.exercise.name
        if name not in recent_names:
            recent_names.append(name)

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

    # 🔥 GET STANDARD EXERCISES FOR THIS MUSCLE
    standard = STANDARD_EXERCISES.get(session.muscle, [])

    # 🔥 GET DATABASE EXERCISES
    db_exercises = [ex.name for ex in exercises]

    # 🔥 MERGE BOTH (REMOVE DUPLICATES)
    # 🔥 MERGE + PRIORITIZE RECENT
    all_exercises = []

    # recent first
    all_exercises.extend(recent_names)

    # then rest
    for ex in (standard + db_exercises):
        if ex not in all_exercises:
            all_exercises.append(ex)

    return render_template(
        'add_exercise.html',
        exercises=all_exercises,
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
    week = request.args.get('week')

    from datetime import datetime, timedelta

    # 🔥 FIXED (you had syntax error here)
    current_date = datetime.now().strftime("%Y-%m-%d")

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

    # 🔥 FIX DATE FILTER (important)
    if date:
        query = query.filter(WorkoutSession.date.like(f"{date}%"))

    # 🔥 ADD WEEK FILTER
    if week:
        today = datetime.now()
        week_ago = today - timedelta(days=7)

        query = query.filter(WorkoutSession.date >= week_ago)

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
        total_sets=total_sets,
        current_date=current_date   # 🔥 IMPORTANT
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


@app.route('/import_csv', methods=['GET', 'POST'])
def import_csv():

    if request.method == 'POST':

        file = request.files.get('file')

        if not file:
            return "No file uploaded"

        stream = TextIOWrapper(file.stream, encoding='utf-8')
        reader = csv.DictReader(stream)

        session_map = {}  # (date, muscle) → session
        exercise_map = {}  # exercise name → Exercise object

        imported_count = 0

        for row in reader:
            date = row['Date']
            muscle = row['Muscle'].strip().lower()
            exercise_name = row['Exercise'].strip().lower()
            weight = float(row['Weight'])
            reps = int(row['Reps'])

            # 🔷 SESSION
            session_key = (date, muscle)

            if session_key not in session_map:
                session = WorkoutSession(date=date, muscle=muscle)
                db.session.add(session)
                db.session.flush()  # get id without commit
                session_map[session_key] = session
            else:
                session = session_map[session_key]

            # 🔷 EXERCISE
            if exercise_name not in exercise_map:
                exercise = Exercise.query.filter_by(name=exercise_name).first()
                if not exercise:
                    exercise = Exercise(name=exercise_name)
                    db.session.add(exercise)
                    db.session.flush()
                exercise_map[exercise_name] = exercise
            else:
                exercise = exercise_map[exercise_name]

            # 🔷 EXERCISE LOG (CHECK EXISTING)
            log = ExerciseLog.query.filter_by(
                session_id=session.id,
                exercise_id=exercise.id
            ).first()

            if not log:
                log = ExerciseLog(session_id=session.id, exercise_id=exercise.id)
                db.session.add(log)
                db.session.flush()

            # 🔷 SET LOG
            set_count = SetLog.query.filter_by(exercise_log_id=log.id).count()

            new_set = SetLog(
                exercise_log_id=log.id,
                set_number=set_count + 1,
                weight=weight,
                reps=reps
            )

            db.session.add(new_set)

            imported_count += 1

        db.session.commit()

        return f"✅ Imported {imported_count} rows successfully!"

    return render_template('import_csv.html')



@app.route('/delete_set/<int:set_id>')
def delete_set(set_id):

    set_log = SetLog.query.get_or_404(set_id)

    db.session.delete(set_log)
    db.session.commit()

    return redirect(url_for('dashboard'))

@app.route('/edit_set/<int:set_id>', methods=['GET', 'POST'])
def edit_set(set_id):

    set_log = SetLog.query.get_or_404(set_id)

    if request.method == 'POST':
        set_log.weight = float(request.form['weight'])
        set_log.reps = int(request.form['reps'])

        db.session.commit()

        return redirect(url_for('dashboard'))

    return render_template('edit_set.html', set_log=set_log)

# -------------------------
# RUN
# -------------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5001)