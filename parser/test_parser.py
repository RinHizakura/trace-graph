#!/usr/bin/env python3
"""Smallest check that fails if the ftrace/dmesg event handlers break."""
from dmesg_parser import parse_dmesg_line
from ftrace_parser import (
    DurationTracker,
    handle_sched_swtich_event,
    handle_cpu_idle_event,
    handle_bio_start_event,
    handle_bio_end_event,
    handle_nvme_setup_event,
    handle_nvme_complete_event,
    handle_irq_handler_start_event,
    handle_irq_handler_end_event,
    handle_softirq_start_event,
    handle_softirq_end_event,
)


def test_sched_switch():
    # fio runs on CPU2 from t=100, switched out at t=180
    d = DurationTracker()
    exit_info = handle_sched_swtich_event(
        "prev_comm=swapper/2 prev_pid=0 prev_prio=120 prev_state=R "
        "==> next_comm=fio next_pid=1234 next_prio=120",
        2,
        d,
        100,
    )
    assert exit_info is None, exit_info
    exit_info = handle_sched_swtich_event(
        "prev_comm=fio prev_pid=1234 prev_prio=120 prev_state=S "
        "==> next_comm=swapper/2 next_pid=0 next_prio=120",
        2,
        d,
        180,
    )
    assert exit_info == ("fio-1234", 100, 80), exit_info


def test_cpu_idle():
    # 4294967295 means exit-idle (state 0), otherwise state+1
    assert handle_cpu_idle_event("state=4294967295 cpu_id=3") == ("CPU003", 0)
    assert handle_cpu_idle_event("state=1 cpu_id=3") == ("CPU003", 2)


def test_bio():
    # issue on CPU0, complete on CPU4 must still match (no cpu in key)
    d = DurationTracker()
    handle_bio_start_event(
        "179,0 WFSM 4096 () 58339640 + 8 [kworker/0:1H]", "kworker/0:1H-152", d, 100
    )
    exit_info = handle_bio_end_event("179,0 WFSM () 58339640 + 8 [0]", d, 250)
    assert exit_info == ("kworker/0:1H-152", 100, 150), exit_info


def test_nvme():
    # cmdid 8202 = genctr 2 << 12 | tag 10; io and admin (no disk=) forms
    d = DurationTracker()
    handle_nvme_setup_event(
        "nvme0: disk=nvme0n1, qid=1, cmdid=8202, nsid=1, flags=0x0, meta=0x0, "
        "cmd=(nvme_cmd_read slba=190896, len=7, ctrl=0x0, dsmgmt=0, reftag=0)",
        "fio-59507",
        d,
        100,
    )
    track, exit_info = handle_nvme_complete_event(
        "nvme0: disk=nvme0n1, qid=1, cmdid=8202, res=0x0, retries=0, flags=0x0, status=0x0",
        d,
        400,
    )
    assert track == "nvme0-q1", track
    assert exit_info == ("nvme_cmd_read tag=10 fio-59507", 100, 300), exit_info

    handle_nvme_setup_event(
        "nvme0: qid=0, cmdid=4106, nsid=0, flags=0x0, meta=0x0, "
        "cmd=(nvme_admin_get_log_page cdw10=...)",
        "nvme-1234",
        d,
        500,
    )
    track, exit_info = handle_nvme_complete_event(
        "nvme0: qid=0, cmdid=4106, res=0x0, retries=0, flags=0x0, status=0x0", d, 600
    )
    assert track == "nvme0-q0", track
    assert exit_info == ("nvme_admin_get_log_page tag=10 nvme-1234", 500, 100), exit_info


def test_irq_handler():
    # entry/exit matched per irq number and cpu
    d = DurationTracker()
    handle_irq_handler_start_event("irq=130 name=nvme0q1", 4, d, 100)
    exit_info = handle_irq_handler_end_event("irq=130 ret=handled", 4, d, 130)
    assert exit_info == ("nvme0q1", 100, 30), exit_info


def test_softirq():
    # entry/exit matched per vec and cpu
    d = DurationTracker()
    handle_softirq_start_event("vec=4 [action=BLOCK]", 4, d, 200)
    exit_info = handle_softirq_end_event("vec=4", 4, d, 260)
    assert exit_info == ("BLOCK", 200, 60), exit_info


def test_dmesg():
    # /dev/kmsg record: pri 6 = facility 0, severity 6 (info)
    parsed = parse_dmesg_line("6,1234,71167229495,-;nvme nvme0: I/O tag 10 timeout\n")
    assert parsed == (6, 71167.229495, "nvme nvme0: I/O tag 10 timeout"), parsed
    # facility folds away: pri 30 = facility 3, severity 6
    assert parse_dmesg_line("30,1,5000000,-;msg")[0] == 6
    # continuation lines are skipped
    assert parse_dmesg_line(" SUBSYSTEM=pci\n") is None


if __name__ == "__main__":
    test_sched_switch()
    test_cpu_idle()
    test_bio()
    test_nvme()
    test_irq_handler()
    test_softirq()
    test_dmesg()
    print("ok")
