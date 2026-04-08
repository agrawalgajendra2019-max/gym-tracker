def calculate_volume(weight, reps):
    return weight * reps


def calculate_total_volume(logs):
    return sum(log.weight * log.reps for log in logs)


# 🔥 NEW: get previous weight
def get_previous_weight(current_log, all_logs):
    exercise_name = current_log.exercise_log.exercise.name

    previous_logs = [
        log for log in all_logs
        if log.exercise_log.exercise.name == exercise_name
        and log.id < current_log.id
    ]

    if not previous_logs:
        return None

    # latest previous
    previous_logs.sort(key=lambda x: x.id)
    return previous_logs[-1].weight


# 🔥 NEW: improvement %
def calculate_improvement(current, previous):
    if previous is None or previous == 0:
        return None

    return round(((current - previous) / previous) * 100, 2)