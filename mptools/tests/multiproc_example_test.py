import os
import socket
import threading

from examples import mptools_example
from examples.mptools_example import (
    _close_queue,
    EventMessage,
    StatusWorker,
    ObservationWorker,
    SendWorker,
    ListenWorker,
)
from mptools_test import _proc_worker_wrapper_helper

def test_status_worker(caplog):
    class TestStatusWorker(StatusWorker):
        INTERVAL_SECS = 0.1
        _calls = 0

        def get_status(self):
            self._calls += 1
            return "OKAY" if self._calls % 2 else "NOT-OKAY"

    items = _proc_worker_wrapper_helper(caplog, TestStatusWorker, alarm_secs=0.5)
    assert len(items) >= 9
    for idx, item in enumerate(items):
        assert item.msg_src == "TEST", item
        assert item.msg_type == "STATUS", item
        assert item.msg == "NOT-OKAY" if idx % 2 else "OKAY", item


def test_observation_worker(caplog):
    class TestObservationWorker(ObservationWorker):
        INTERVAL_SECS = 0.1

    items = _proc_worker_wrapper_helper(caplog, TestObservationWorker, alarm_secs=0.5)
    assert len(items) >= 9
    for idx, item in enumerate(items):
        assert item.msg_src == "TEST", item
        assert item.msg_type == "OBSERVATION", item
        assert item.msg == "SOME DATA", item


def test_send_worker(caplog):
    TEST_FILE_NAME = "test_send_file.txt"
    class TestSendWorker(SendWorker):
        def startup(self):
            self.send_file = open(TEST_FILE_NAME, "w")

    send_q = mptools_example.Queue()
    send_q.put(EventMessage("TEST", "OBSERVATION", "SOME DATA 1"))
    send_q.put(EventMessage("TEST", "OBSERVATION", "SOME DATA 2"))
    send_q.put(EventMessage("TEST", "OBSERVATION", "SOME DATA 3"))
    send_q.put(EventMessage("TEST", "OBSERVATION", "SOME DATA 4"))
    send_q.put(EventMessage("TEST", "OBSERVATION", "SOME DATA 5"))

    try:
        items = _proc_worker_wrapper_helper(caplog, TestSendWorker, args=(send_q,), expect_shutdown_evt=True, alarm_secs=1)
        assert items == []
        with open("test_send_file.txt", "r") as f:
            for idx, line in enumerate(f):
                assert line == f"OBSERVATION::SOME DATA {idx + 1}\n"
    finally:
        _close_queue(send_q)
        if os.path.exists(TEST_FILE_NAME):
            os.remove(TEST_FILE_NAME)

def test_listen_worker(caplog):
    class TestListenWorker(ListenWorker):
        def _test_hook(self):
            request = self.event_q.get()
            assert request.msg == f"REQUEST {self._test_hook_idx + 1}"
            self.reply_q.put(request.msg.replace("REQUEST", "REPLY"))

    startup_evt = mptools_example.Event()
    shutdown_evt = mptools_example.Event()
    event_q = mptools_example.Queue()
    reply_q = mptools_example.Queue()
    lw = TestListenWorker('TEST', startup_evt, shutdown_evt, event_q, reply_q)
    try:
        lw.startup()

        NUM_TO_PROCESS = 5

        def thread_worker():
            for idx in range(NUM_TO_PROCESS):
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect(('127.0.0.1', 9999))
                try:
                    sock.send(f"REQUEST {idx + 1}".encode("utf-8"))
                    reply = sock.recv(1500).decode()
                    assert reply == f"REPLY {idx + 1}"
                finally:
                    sock.close()

        t = threading.Thread(target=thread_worker)
        t.start()

        for idx in range(NUM_TO_PROCESS):
            lw._test_hook_idx = idx
            lw.main_func()

        t.join()
    finally:
        lw.shutdown()

    _close_queue(event_q)
    _close_queue(reply_q)
