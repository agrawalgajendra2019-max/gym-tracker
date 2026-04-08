def get_max_weight(exercise_name, logs):
    weights = [
        log.weight for log in logs
        if log.exercise_log.exercise.name == exercise_name
    ]
    return max(weights) if weights else 0


def is_pr(set_log, all_logs):
    exercise_name = set_log.exercise_log.exercise.name

    max_weight = get_max_weight(
        exercise_name,
        all_logs
    )

    return set_log.weight >= max_weight


def suggest_weight(exercise_name, all_logs):
    max_weight = get_max_weight(exercise_name, all_logs)
    return max_weight + 2.5 if max_weight else 0