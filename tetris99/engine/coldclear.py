"""ctypes binding for Cold Clear's C API (third_party/cold-clear/c-api/coldclear.h)."""
from __future__ import annotations

import ctypes as C
import json
import os
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from .board import Board, COLS

_ROOT = Path(__file__).resolve().parent.parent.parent
_LIB_CANDIDATES = [
    os.environ.get("COLD_CLEAR_LIB", ""),
    str(_ROOT / "third_party/cold-clear/target/release/libcold_clear.so"),
    str(_ROOT / "lib/libcold_clear.so"),
]

PIECES = "IOTLJSZ"  # CCPiece enum order


class Movement(IntEnum):
    LEFT = 0
    RIGHT = 1
    CW = 2
    CCW = 3
    DROP = 4  # soft drop to floor


class PollStatus(IntEnum):
    MOVE_PROVIDED = 0
    WAITING = 1
    BOT_DEAD = 2


class CCPlanPlacement(C.Structure):
    _fields_ = [
        ("piece", C.c_int), ("tspin", C.c_int),
        ("expected_x", C.c_uint8 * 4), ("expected_y", C.c_uint8 * 4),
        ("cleared_lines", C.c_int32 * 4),
    ]


class CCMove(C.Structure):
    _fields_ = [
        ("hold", C.c_bool),
        ("expected_x", C.c_uint8 * 4), ("expected_y", C.c_uint8 * 4),
        ("movement_count", C.c_uint8), ("movements", C.c_int * 32),
        ("nodes", C.c_uint32), ("depth", C.c_uint32), ("original_rank", C.c_uint32),
    ]


class CCOptions(C.Structure):
    _fields_ = [
        ("mode", C.c_int), ("spawn_rule", C.c_int), ("pcloop", C.c_int),
        ("min_nodes", C.c_uint32), ("max_nodes", C.c_uint32), ("threads", C.c_uint32),
        ("use_hold", C.c_bool), ("speculate", C.c_bool),
    ]


class CCWeights(C.Structure):
    _fields_ = [(name, C.c_int32) for name in (
        "back_to_back", "bumpiness", "bumpiness_sq", "row_transitions", "height", "top_half",
        "top_quarter", "jeopardy", "cavity_cells", "cavity_cells_sq", "overhang_cells",
        "overhang_cells_sq", "covered_cells", "covered_cells_sq")] + [
        ("tslot", C.c_int32 * 4), ("well_depth", C.c_int32), ("max_well_depth", C.c_int32),
        ("well_column", C.c_int32 * 10)] + [(name, C.c_int32) for name in (
        "b2b_clear", "clear1", "clear2", "clear3", "clear4", "tspin1", "tspin2", "tspin3",
        "mini_tspin1", "mini_tspin2", "perfect_clear", "combo_garbage", "move_time", "wasted_t")] + [
        ("use_bag", C.c_bool), ("timed_jeopardy", C.c_bool), ("stack_pc_damage", C.c_bool),
    ]


WEIGHT_FIELDS = [name for name, _ in CCWeights._fields_]


def weights_to_dict(w: CCWeights) -> dict:
    out = {}
    for name in WEIGHT_FIELDS:
        v = getattr(w, name)
        out[name] = list(v) if hasattr(v, "__len__") else v
    return out


def apply_weights(w: CCWeights, overrides: dict) -> None:
    """Set fields of a CCWeights struct from a dict. Unknown keys are an error so typos surface."""
    for name, v in overrides.items():
        if name.startswith("_"):
            continue  # allow "_comment" style keys
        if name not in WEIGHT_FIELDS:
            raise KeyError(f"unknown Cold Clear weight {name!r}; valid: {', '.join(WEIGHT_FIELDS)}")
        cur = getattr(w, name)
        if hasattr(cur, "__len__"):
            if len(v) != len(cur):
                raise ValueError(f"{name} needs {len(cur)} values, got {len(v)}")
            for i, x in enumerate(v):
                cur[i] = int(x)
        elif isinstance(cur, bool):
            setattr(w, name, bool(v))
        else:
            setattr(w, name, int(v))


def load_weights(path: "str | Path") -> dict:
    return json.loads(Path(path).read_text())


def default_weights(fast: bool = False) -> dict:
    w = CCWeights()
    (lib().cc_fast_weights if fast else lib().cc_default_weights)(C.byref(w))
    return weights_to_dict(w)


def _load() -> C.CDLL:
    for p in _LIB_CANDIDATES:
        if p and Path(p).exists():
            lib = C.CDLL(p)
            break
    else:
        raise FileNotFoundError("libcold_clear.so not found; build with: cargo build --release -p c-api in third_party/cold-clear")
    P = C.POINTER
    lib.cc_launch_async.restype = C.c_void_p
    lib.cc_launch_async.argtypes = [P(CCOptions), P(CCWeights), C.c_void_p, P(C.c_int), C.c_uint32]
    lib.cc_launch_with_board_async.restype = C.c_void_p
    lib.cc_launch_with_board_async.argtypes = [P(CCOptions), P(CCWeights), C.c_void_p, P(C.c_bool), C.c_uint32,
                                               P(C.c_int), C.c_bool, C.c_uint32, P(C.c_int), C.c_uint32]
    lib.cc_destroy_async.argtypes = [C.c_void_p]
    lib.cc_reset_async.argtypes = [C.c_void_p, P(C.c_bool), C.c_bool, C.c_uint32]
    lib.cc_add_next_piece_async.argtypes = [C.c_void_p, C.c_int]
    lib.cc_request_next_move.argtypes = [C.c_void_p, C.c_uint32]
    lib.cc_poll_next_move.restype = C.c_int
    lib.cc_poll_next_move.argtypes = [C.c_void_p, P(CCMove), P(CCPlanPlacement), P(C.c_uint32)]
    lib.cc_block_next_move.restype = C.c_int
    lib.cc_block_next_move.argtypes = [C.c_void_p, P(CCMove), P(CCPlanPlacement), P(C.c_uint32)]
    lib.cc_default_options.argtypes = [P(CCOptions)]
    lib.cc_default_weights.argtypes = [P(CCWeights)]
    lib.cc_fast_weights.argtypes = [P(CCWeights)]
    return lib


_lib: C.CDLL | None = None


def lib() -> C.CDLL:
    global _lib
    if _lib is None:
        _lib = _load()
    return _lib


@dataclass
class Move:
    hold: bool
    cells: list[tuple[int, int]]      # (x, y), y=0 bottom
    movements: list[Movement]
    nodes: int
    depth: int

    @classmethod
    def from_c(cls, m: CCMove) -> "Move":
        return cls(
            hold=m.hold,
            cells=[(m.expected_x[i], m.expected_y[i]) for i in range(4)],
            movements=[Movement(m.movements[i]) for i in range(m.movement_count)],
            nodes=m.nodes, depth=m.depth,
        )


@dataclass
class PlanStep:
    piece: str
    cells: list[tuple[int, int]]
    cleared: list[int]   # rows this placement clears

    @classmethod
    def from_c(cls, p: CCPlanPlacement) -> "PlanStep":
        return cls(PIECES[p.piece], [(p.expected_x[i], p.expected_y[i]) for i in range(4)],
                   [int(p.cleared_lines[i]) for i in range(4) if p.cleared_lines[i] >= 0])


def valid_sequence(pieces: "str | list[str]", hold: str | None = None) -> bool:
    """7-bag sanity: every entry is a piece letter, and no piece occurs more than twice within any
    7 consecutive pieces of the sequence (7 consecutive pieces span at most two bags). The hold
    piece only has to be a valid letter: it left the sequence earlier, so it is not bound by the
    window. Cold Clear aborts the whole process on an impossible bag, so this is checked before
    anything reaches it."""
    seq = list(pieces)
    if any(p not in PIECES for p in seq) or (hold is not None and hold not in PIECES):
        return False
    for i in range(len(seq)):
        window = seq[i : i + 7]
        if any(window.count(p) > 2 for p in set(window)):
            return False
    return True


def board_to_field(board: Board) -> C.Array:
    field = (C.c_bool * 400)()
    for y in range(40):
        row = board.rows[y]
        for x in range(COLS):
            field[y * COLS + x] = bool(row >> x & 1)
    return field


class ColdClear:
    """One bot instance. Pieces are single-letter strings from PIECES."""

    def __init__(self, queue: str = "", *, threads: int = 2, max_nodes: int = 100_000,
                 board: Board | None = None, hold: str | None = None, bag_remain: str | None = None,
                 speculate: bool = True, fast_weights: bool = False,
                 weights: "dict | str | Path | None" = None, pcloop: int = 0):
        """pcloop: 0 off, 1 CC_PC_FASTEST, 2 CC_PC_ATTACK (perfect-clear solver from an empty board)."""
        if not valid_sequence(queue, hold):
            raise ValueError(f"impossible piece sequence for 7-bag: hold={hold} queue={queue}")
        L = lib()
        self.opts = CCOptions()
        L.cc_default_options(C.byref(self.opts))
        self.opts.threads = threads
        self.opts.max_nodes = max_nodes
        self.opts.speculate = speculate
        self.opts.pcloop = pcloop
        self.weights = CCWeights()
        (L.cc_fast_weights if fast_weights else L.cc_default_weights)(C.byref(self.weights))
        if weights is not None:
            apply_weights(self.weights, load_weights(weights) if not isinstance(weights, dict) else weights)

        q = (C.c_int * max(1, len(queue)))(*[PIECES.index(p) for p in queue])
        if board is None:
            self.bot = L.cc_launch_async(C.byref(self.opts), C.byref(self.weights), None, q, len(queue))
        else:
            bag = 0
            for p in (bag_remain if bag_remain is not None else PIECES):
                bag |= 1 << PIECES.index(p)
            hold_c = C.c_int(PIECES.index(hold)) if hold else None
            self.bot = L.cc_launch_with_board_async(
                C.byref(self.opts), C.byref(self.weights), None, board_to_field(board), bag,
                C.byref(hold_c) if hold_c is not None else None, False, 0, q, len(queue))
        if not self.bot:
            raise RuntimeError("cc_launch failed")
        self.plan: list[PlanStep] = []

    def add_next_piece(self, piece: str) -> None:
        lib().cc_add_next_piece_async(self.bot, PIECES.index(piece))

    def reset(self, board: Board, b2b: bool = False, combo: int = 0) -> None:
        lib().cc_reset_async(self.bot, board_to_field(board), b2b, combo)

    def request_move(self, incoming: int = 0) -> None:
        lib().cc_request_next_move(self.bot, incoming)

    def poll_move(self, plan_len: int = 0) -> tuple[PollStatus, Move | None]:
        """Poll for the requested move. With plan_len > 0, also fetch the bot's intended follow-up
        placements into self.plan (a list of PlanStep, first entry = this move)."""
        m = CCMove()
        if plan_len:
            plan = (CCPlanPlacement * plan_len)()
            n = C.c_uint32(plan_len)
            status = PollStatus(lib().cc_poll_next_move(self.bot, C.byref(m), plan, C.byref(n)))
            self.plan = [PlanStep.from_c(plan[i]) for i in range(n.value)] if status is PollStatus.MOVE_PROVIDED else []
        else:
            status = PollStatus(lib().cc_poll_next_move(self.bot, C.byref(m), None, None))
        return status, (Move.from_c(m) if status is PollStatus.MOVE_PROVIDED else None)

    def block_move(self) -> Move | None:
        """Returns None if the bot decided it is dead."""
        m = CCMove()
        status = PollStatus(lib().cc_block_next_move(self.bot, C.byref(m), None, None))
        return Move.from_c(m) if status is PollStatus.MOVE_PROVIDED else None

    def close(self) -> None:
        if self.bot:
            lib().cc_destroy_async(self.bot)
            self.bot = None

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
