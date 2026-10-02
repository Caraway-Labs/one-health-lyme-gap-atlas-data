"""Real spawned local children only; no Snowflake or network operations."""

import time

from lyme_gap_atlas_data import failure_engine_launcher as launcher
from lyme_gap_atlas_data import failure_engine_proof as proof


def successful(channel, cancel):
    channel.send({"state": "PASS", "cleanup": "PASS"})
    channel.close()


def failed(channel, cancel):
    channel.send({"state": "FAIL", "cleanup": "UNKNOWN"})
    channel.close()


def waiting(channel, cancel):
    while not cancel.wait(0.01):
        pass
    channel.send({"state": "FAIL", "cleanup": "PASS"})
    channel.close()


def stuck(channel, cancel):
    time.sleep(30)


def vanished(channel, cancel):
    channel.close()


def private_failure(channel, cancel):
    import snowflake.connector

    def denied(**kwargs):
        print("private-driver-diagnostic")
        raise RuntimeError("private-error-never-publish")

    snowflake.connector.connect = denied
    launcher._child(channel, cancel, {}, "approved", "private-user")


def test_no_approval_or_bad_plan_never_spawns(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("spawn forbidden")

    monkeypatch.setattr(launcher, "_supervise", forbidden)
    plan = proof.make_plan("a" * 40)
    assert launcher.launch_proof(plan)["state"] == "NOT_AUTHORIZED"
    assert (
        launcher.launch_proof(plan, approved_plan_sha256="wrong", expected_user="private")["state"]
        == "PLAN_REJECTED"
    )


def test_real_child_success_and_original_failure():
    assert launcher._supervise(successful, (), seconds=10)["receipt"]["state"] == "PASS"
    assert launcher._supervise(failed, (), seconds=10)["receipt"]["state"] == "FAIL"


def test_cooperative_timeout_reserves_cleanup():
    result = launcher._supervise(waiting, (), seconds=5)
    assert result["receipt"] == {"state": "FAIL", "cleanup": "PASS"}
    assert result["server_query_cancellation"] == "UNKNOWN"


def test_stuck_child_is_terminated_and_unrelated_child_survives():
    context = launcher.multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    other_cancel = context.Event()
    other = context.Process(target=stuck, args=(sender, other_cancel))
    other.start()
    try:
        start = time.monotonic()
        result = launcher._supervise(stuck, (), seconds=2)
        assert time.monotonic() - start < 5
        assert result["receipt"] == {"state": "OUTER_TIMEOUT", "cleanup": "UNKNOWN"}
        assert other.is_alive()
    finally:
        other.terminate()
        other.join(5)
        receiver.close()
        sender.close()


def test_child_disappearing_preserves_unknown_cleanup():
    assert launcher._supervise(vanished, (), seconds=5)["receipt"] == {
        "state": "CHILD_FAILURE",
        "cleanup": "UNKNOWN",
    }


def test_child_driver_output_and_exception_are_not_published(capfd):
    result = launcher._supervise(private_failure, (), seconds=10)
    assert result["receipt"] == {"state": "CHILD_FAILURE", "cleanup": "UNKNOWN"}
    assert capfd.readouterr() == ("", "")
