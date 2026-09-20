"""Registration quality gate using the runtime dynamic matcher, without I/O."""
import time

import numpy as np

from custom_motion import MATCH_DISTANCE, motion_matching_distance


def evaluate_dynamic_takes(sequences, hand_count, reference_data=None):
    """Exclude the query take; require every take to recognize a peer.

    Scores, strict threshold and first-candidate tie handling match update().
    Existing templates precede pending templates, as they do after append.
    This validates full sequences, not the runtime completion state machine.
    """
    started = time.perf_counter()
    count = len(sequences)
    pairs, rows = [], []
    accepted = np.zeros((count, count), dtype=bool)
    distances = np.full((count, count), np.inf)
    for i, query in enumerate(sequences):
        for j, reference in enumerate(sequences):
            if i == j:
                continue
            score = float(motion_matching_distance(query, reference, hand_count))
            distances[i, j] = score
            accepted[i, j] = np.isfinite(score) and score < MATCH_DISTANCE
            pairs.append(dict(query_take=i + 1, reference_take=j + 1,
                              score=score if np.isfinite(score) else None,
                              accepted=bool(accepted[i, j])))
        best_score, best_name, best_take = MATCH_DISTANCE, None, None
        if reference_data is not None:
            for reference, name, motion, hands in zip(
                    *(reference_data[k] for k in
                      ('sequences', 'sequence_names', 'motions', 'hand_counts'))):
                if motion != 'DYNAMIC' or int(hands) != hand_count:
                    continue
                score = float(motion_matching_distance(query, reference, hand_count))
                if np.isfinite(score) and score < best_score:
                    best_score, best_name = score, str(name)
        for j in range(count):
            if accepted[i, j] and distances[i, j] < best_score:
                best_score, best_name, best_take = float(distances[i, j]), None, j + 1
        rows.append(dict(take=i + 1, passed=best_take is not None,
                         peer_match=bool(accepted[i].any()),
                         matched_take=best_take, competing_name=best_name,
                         score=best_score if best_take is not None or best_name is not None else None))
    passed = count >= 2 and all(row['passed'] for row in rows)
    # Name an outlier only when all remaining takes mutually agree and the
    # outlier fails in both directions with every remaining take.
    outliers = []
    if count >= 3:
        for i in range(count):
            peers = [j for j in range(count) if j != i]
            if (not accepted[i].any() and not accepted[:, i].any()
                    and all(accepted[j, k] for j in peers for k in peers if j != k)):
                outliers.append(i + 1)
    outlier = outliers[0] if len(outliers) == 1 else None
    if passed:
        reason = ''
    elif count < 2:
        reason = '회차 간 비교에 필요한 촬영이 부족합니다. 다시 촬영해주세요'
    elif outlier is not None:
        reason = f'{outlier}회차 동작이 다른 회차와 다릅니다. {outlier}회차를 다시 촬영해주세요'
    elif any(row['competing_name'] is not None for row in rows):
        reason = '촬영한 동작이 실행 시 다른 등록 제스처로 인식됩니다. 구분되는 동작으로 다시 촬영해주세요'
    else:
        reason = '촬영 회차의 동작이 실행 인식 기준에서 서로 다릅니다. 같은 동작으로 다시 촬영해주세요'
    return dict(passed=passed, reason=reason, outlier_take=outlier,
                threshold=MATCH_DISTANCE, comparison='strict_less_than',
                pairs=pairs, takes=rows,
                elapsed_ms=(time.perf_counter() - started) * 1000)
