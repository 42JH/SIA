"""Compare the same dynamic traces with 2D-only and 2D+world scoring."""
import json
import time
from pathlib import Path
import numpy as np
from custom_motion import FRAMES, motion_comparison, MATCH_DISTANCE


def trace(depth=0.0):
    xy = np.zeros((FRAMES, 1, 21, 2), np.float32)
    world = np.zeros((FRAMES, 1, 21, 3), np.float32)
    for i in range(FRAMES):
        xy[i, 0, :, 0] = i*.01
        world[i, 0, :, 0] = i*.01
    world[:, 0, 8, 2] = np.linspace(0, depth, FRAMES)
    return xy, world


def main():
    same = trace(0.0)
    depth_mismatch = trace(.8)
    cases=[]
    for label, a, b in [('same', same, same), ('depth_mismatch', same, depth_mismatch)]:
        t=[]
        for _ in range(1000):
            start=time.perf_counter(); two=motion_comparison(a[0],b[0],1)['score'];
            three=motion_comparison(a[0],b[0],1,world_a=a[1],world_b=b[1])['score']
            t.append((time.perf_counter()-start)*1000)
        cases.append(dict(name=label, score_2d=float(two), score_2d_world_3d=float(three),
                          two_d_match=two < MATCH_DISTANCE, combined_match=three < MATCH_DISTANCE,
                          p50_ms=float(np.percentile(t,50)),p95_ms=float(np.percentile(t,95))))
    report=dict(cases=cases, threshold=MATCH_DISTANCE, iterations=1000,
                current_registered_templates='This worktree does not modify existing BE templates; dynamic 3D is used only when a new capture stores valid world data.',
                limitation='Synthetic depth perturbation and repeated in-memory comparisons; not camera accuracy.')
    out=Path(__file__).resolve().parent.parent/'Docs/dynamic-2d-vs-3d-evaluation.json'
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
