from tetris99.engine.board import Board
from tetris99.engine.explore import reachable_placements
from tetris99.engine.game import Game
from tetris99.sandbox.lessons import BY_KEY, LESSONS, board_from


def test_bag_and_hold_and_undo():
    g = Game(seed=1)
    first = g.piece.kind
    assert len(g.next_queue()) == 6
    assert g.use_hold() and g.hold == first and g.hold_used
    assert not g.use_hold()                      # once per piece
    g.hard_drop()
    assert g.stats["pieces"] == 1 and not g.hold_used
    assert g.undo() and g.stats["pieces"] == 0   # undo the placement
    assert g.undo() and g.hold is None           # undo the hold
    assert g.redo() and g.hold == first
    assert g.redo() and g.stats["pieces"] == 1


def test_explorer_counts_i_placements_on_empty_board():
    pl = reachable_placements(Board(), "I")
    assert len(pl) == 17   # 7 horizontal + 10 vertical


def spin_solutions(lesson):
    """All reachable placements of the lesson's first piece that lock as its goal."""
    out = []
    for pl in reachable_placements(board_from(lesson.rows), lesson.queue[0]):
        g = Game(seed=0)
        lesson.load(g)
        g.piece = type(pl.piece)(pl.piece.kind, pl.piece.rot, pl.piece.x, pl.piece.y)
        g.last_was_rotation = pl.spin
        g.last_kick = None
        # replay the path so the kick index is recorded like a real player would produce it
        g.piece = type(pl.piece)(pl.piece.kind)  # respawn
        g.piece.x, g.piece.y, g.piece.rot = 4, 19, 0
        for mv in pl.path:
            if mv == "L": g.move(-1)
            elif mv == "R": g.move(1)
            elif mv == "CW": g.rotate(True)
            elif mv == "CCW": g.rotate(False)
            else: g.sonic_drop()
        lk = g.lock()
        if lesson.done(g, lk):
            out.append((pl, lk))
    return out


def test_tsd_lesson_is_solvable_by_a_spin():
    sols = spin_solutions(BY_KEY["1"])
    assert sols, "no T-spin double reachable on the TSD lesson board"
    assert all(lk.tspin == "full" and lk.lines == 2 for _, lk in sols)


def test_tst_lesson_needs_a_kick():
    sols = spin_solutions(BY_KEY["2"])
    assert sols, "no T-spin triple reachable on the TST lesson board"
    assert any(lk.kick not in (None, 0) for _, lk in sols), "expected the TST to require a kick"


def test_lock_kinds_and_attack():
    g = Game(seed=0)
    b = Board(); b.rows[0] = b.rows[1] = b.rows[2] = b.rows[3] = 0b1111111110  # column 0 open, 4 rows
    g.set_state(b, ["I", "O"])
    g.rotate(True); [g.move(-1) for _ in range(6)]
    lk = g.hard_drop()
    assert lk.kind == "tetris" and lk.lines == 4 and lk.perfect_clear
    assert lk.attack == 4 + 10  # tetris + perfect clear bonus
