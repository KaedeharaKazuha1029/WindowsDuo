"""串口探测和按需抓屏回归。运行 python -m unittest discover -s win。"""
import itertools
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from glass_overlay import AngleReader, CaptureWorker, GlassGLWidget, parse_angles


class SerialTests(unittest.TestCase):
    def test_skips_silent_port_then_reads_fragmented_firmware_output(self):
        reader = AngleReader("auto", 115200)
        opened = []
        samples = iter([b'{"temperature":25}\n', b'[log] {"a":12', b',"b":-8}\n'])

        def open_port(port, *args, **kwargs):
            opened.append(port)
            stream = MagicMock()
            def read(**kwargs):
                if port == "COM1":
                    return b""
                chunk = next(samples, None)
                if chunk is None:
                    self.assertEqual(reader.get()[:2], (-8, 12))
                    self.assertEqual(reader.active, "COM2")
                    self.assertTrue(reader.sample_ready.is_set())
                    reader.stopping.set()
                    return b""
                self.assertIsNone(reader.active)
                return chunk
            stream.__enter__.return_value.read_until.side_effect = read
            return stream

        with patch.object(reader, "_ports", return_value=["COM1", "COM2"]), \
             patch("glass_overlay.time") as clock, \
             patch("glass_overlay.serial.Serial", side_effect=open_port), \
             patch.dict("glass_overlay.CFG", axis="b"):
            clock.monotonic.side_effect = itertools.count()
            reader.run()
        self.assertEqual(opened, ["COM1", "COM2"])
        self.assertIsNone(reader.get()[0])
        self.assertFalse(reader.sample_ready.is_set())

    def test_explicit_port_can_finish_calibrating_after_probe_timeout(self):
        reader = AngleReader("COM5", 115200)
        stream = MagicMock()
        def reads():
            yield from [b""] * 10
            yield b'{"a":-90,"b":0}\r\n'
            self.assertEqual(reader.get()[:2], (-90, 0))
            reader.stopping.set()
            yield b""
        stream.__enter__.return_value.read_until.side_effect = reads()
        with patch("glass_overlay.time") as clock, \
             patch("glass_overlay.serial.Serial", return_value=stream) as opened:
            clock.monotonic.side_effect = itertools.count()
            reader._read_loop("COM5")
        opened.assert_called_once()

    def test_rejects_invalid_frames_and_preserves_single_axis_input(self):
        for frame in (b'{}', b'{"b":4}', b'{"a":true}', b'{"a":null}',
                      b'{"a":"bad"}', b'{"a":1,"b":1e999}', b'{"a":NaN}'):
            with self.subTest(frame=frame):
                self.assertIsNone(parse_angles(frame, "a"))
        self.assertEqual(parse_angles(b'{"a":1}', "a"), (1, 0))


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.worker = CaptureWorker({})
        self.widget = SimpleNamespace(capturer=self.worker, _wake_pending=False)

    def wake(self):
        return GlassGLWidget._wake_ready(self.widget)

    def test_static_desktop_reuses_last_frame_after_capture_finishes(self):
        self.worker.frame = (b"old", 1, 1, 1)
        self.worker.done.set()  # prior request finished while visible
        with patch.object(self.worker.done, "wait", side_effect=AssertionError("UI blocked")):
            self.assertFalse(self.wake())
            self.assertFalse(self.worker.done.is_set())
            self.assertFalse(self.wake())
            self.worker._finish_request()  # DXGI returned None
            self.assertTrue(self.wake())

    def test_first_wake_retries_until_a_frame_exists(self):
        self.assertFalse(self.wake())
        self.worker._finish_request()
        self.assertFalse(self.wake())
        self.assertFalse(self.worker.done.is_set())
        self.worker.frame = (b"new", 1, 1, 1)
        self.worker._finish_request()
        self.assertTrue(self.wake())


if __name__ == "__main__":
    unittest.main()
