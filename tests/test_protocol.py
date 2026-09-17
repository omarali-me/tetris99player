from tetris99.control.protocol import Button, Op, encode


def test_encode():
    assert encode(Op.PRESS, Button.A | Button.B) == bytes([0x02, 0x06, 0x00])
    assert encode(Op.WAIT, 300) == bytes([0x05, 0x2C, 0x01])


def test_stick_arg():
    from tetris99.control.protocol import stick_arg
    assert stick_arg(128, 128) == 0x8080
    assert stick_arg(0, 255) == 0xFF00
    assert stick_arg(-5, 300) == 0xFF00
