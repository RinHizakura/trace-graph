#!/usr/bin/env python3
"""Smallest check that fails if bio/nvme duration matching breaks."""
from ftrace_parser import (
    DurationTracker,
    handle_bio_start_event,
    handle_bio_end_event,
    handle_nvme_setup_event,
    handle_nvme_complete_event,
)

d = DurationTracker()

# bio: insert on CPU0, complete on CPU4 must still match (no cpu in key)
handle_bio_start_event("179,0 WFSM 4096 () 58339640 + 8 [kworker/0:1H]", d, 100)
exit_info = handle_bio_end_event("179,0 WFSM () 58339640 + 8 [0]", d, 250)
assert exit_info == ("Comm=kworker/0:1H", 100, 150), exit_info

# nvme: cmdid 8202 = genctr 2 << 12 | tag 10; io and admin (no disk=) forms
handle_nvme_setup_event(
    "nvme0: disk=nvme0n1, qid=1, cmdid=8202, nsid=1, flags=0x0, meta=0x0, "
    "cmd=(nvme_cmd_read slba=190896, len=7, ctrl=0x0, dsmgmt=0, reftag=0)",
    d,
    100,
)
track, exit_info = handle_nvme_complete_event(
    "nvme0: disk=nvme0n1, qid=1, cmdid=8202, res=0x0, retries=0, flags=0x0, status=0x0",
    d,
    400,
)
assert track == "nvme0-q1", track
assert exit_info == ("nvme_cmd_read tag=10", 100, 300), exit_info

handle_nvme_setup_event(
    "nvme0: qid=0, cmdid=4106, nsid=0, flags=0x0, meta=0x0, "
    "cmd=(nvme_admin_get_log_page cdw10=...)",
    d,
    500,
)
track, exit_info = handle_nvme_complete_event(
    "nvme0: qid=0, cmdid=4106, res=0x0, retries=0, flags=0x0, status=0x0", d, 600
)
assert track == "nvme0-q0", track
assert exit_info == ("nvme_admin_get_log_page tag=10", 500, 100), exit_info

print("ok")
