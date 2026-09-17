from tetris99.control.protocol import Button, Op, encode


def test_encode():
    assert encode(Op.PRESS, Button.A | Button.B) == bytes([0x02, 0x06, 0x00])
    assert encode(Op.WAIT, 300) == bytes([0x05, 0x2C, 0x01])
