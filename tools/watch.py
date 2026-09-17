"""Watch the bot play in a window. Runs the real Player (tracker -> Cold Clear -> executor) against
the fake Switch and animates every button press.

Keys: space pause/resume, n single step (while paused), +/- speed, q quit.
"""
from __future__ import annotations

import argparse
import time

import cv2

from tetris99.engine.coldclear import load_weights
from tetris99.loop import Player
from tetris99.render import draw
from tetris99.sim_env import SimEnv


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--pieces", type=int, default=5000)
    ap.add_argument("--garbage-every", type=int, default=12, help="2 garbage lines every N pieces (0 = off)")
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--max-nodes", type=int, default=100_000)
    ap.add_argument("--delay", type=int, default=120, help="ms per animation step")
    ap.add_argument("--think", type=int, default=50, help="ms the bot may think per piece")
    ap.add_argument("--weights", help="JSON file overriding Cold Clear weights (see config/weights.json)")
    args = ap.parse_args()
    weights = load_weights(args.weights) if args.weights else None

    env = SimEnv(seed=args.seed, max_pieces=args.pieces, garbage_every=args.garbage_every)
    player = Player(env, threads=args.threads, max_nodes=args.max_nodes, weights=weights, think_ms=args.think)
    colors: dict[tuple[int, int], str] = {}
    state = {"delay": args.delay, "paused": False, "step": False, "quit": False, "last_actions": ""}
    t_start = time.perf_counter()

    def info():
        g = env.game
        elapsed = time.perf_counter() - t_start
        m = env.meter()
        return [f"pieces  {g.pieces_placed}", f"lines   {g.lines}", f"garbage {m.total} incoming",
                f"height  {g.board.height()}", f"pps     {g.pieces_placed / elapsed:.2f}",
                f"speed   {state['delay']} ms", "", "last move:", state["last_actions"],
                "", "space pause  n step", "+/- speed   q quit"]

    def show():
        m = env.meter()
        img = draw(env.game.board, env.piece, env.game.hold, env.game.queue[1:], colors, info(),
                   garbage_pending=m.pending, garbage_imminent=m.imminent)
        cv2.imshow("tetris99 bot", img)

    def handle_keys(wait_ms: int) -> None:
        while True:
            k = cv2.waitKey(max(1, wait_ms)) & 0xFF
            if k == ord("q"):
                state["quit"] = True
                return
            if k == ord(" "):
                state["paused"] = not state["paused"]
            elif k == ord("n"):
                state["step"] = True
            elif k in (ord("+"), ord("=")):
                state["delay"] = max(0, state["delay"] - 30)
            elif k == ord("-"):
                state["delay"] += 30
            if not state["paused"] or state["step"]:
                state["step"] = False
                return
            show()
            wait_ms = 50

    def on_action(env: SimEnv, action) -> None:
        if action is None:
            # piece just locked: remember its color for the drawing, then show the result
            return
        state["last_actions"] = " ".join(a.kind for a in env.last_actions)
        if action.kind == "hard_drop":
            p = env.piece
            p2 = type(p)(p.kind, p.rot, p.x, p.y)
            p2.sonic_drop(env.game.board)
            for c in p2.cells():
                colors[c] = p.kind
        show()
        handle_keys(state["delay"])
        if state["quit"]:
            raise KeyboardInterrupt

    env.on_action = on_action

    # Line clears and garbage move rows; rebuild the color map from what survives.
    def refresh_colors():
        g = env.game
        survivors = {}
        for (x, y), k in colors.items():
            if g.board.rows[y] >> x & 1:
                survivors[(x, y)] = k
        colors.clear()
        colors.update(survivors)

    try:
        for fs in env.frames():
            refresh_colors()
            show()
            handle_keys(state["delay"])
            if state["quit"]:
                break
            player.step(fs)
    except KeyboardInterrupt:
        pass
    finally:
        player.close()
        cv2.destroyAllWindows()
    g = env.game
    print(f"placed={g.pieces_placed} lines={g.lines} height={g.board.height()} dead={env.dead}")


if __name__ == "__main__":
    main()
