import re
from datetime import datetime
from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig
from drain3.file_persistence import FilePersistence

log_data = [
    "{H1S6-F0IM39KJ-7455MIMK}\t04/13/2011 01:25:14\tDTAA/CDZ0056\tPC-4052\tDisconnect",
    "{P6Q2-N3LI55TV-9405QDSQ}\t04/13/2011 02:24:35\tDTAA/AGW0182\tPC-4531\tConnect",
    "01-04-2010 07:12 DTAA/RES0962 PC-3736 Connect",
    "01-04-2010 08:20 DTAA/RES0962 PC-3736 Disconnect",
    "2010-04-01 08:29:15 DTAA/RQH0770 PC-4225 Connect"
]

config = TemplateMinerConfig()
persistence = FilePersistence("drain3_state.bin")
template_miner = TemplateMiner(persistence, config)

date_formats = [
    "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
    "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"
]

def parse_log(line):
    template_miner.add_log_message(line)
    parts = re.split(r'\s+', line.strip())

    datetime_str = None
    for i in range(len(parts) - 1):
        candidate = parts[i] + " " + parts[i+1]
        for fmt in date_formats:
            try:
                dt = datetime.strptime(candidate, fmt)
                datetime_str = dt
                break
            except ValueError:
                continue
        if datetime_str:
            break

    if not datetime_str:
        return None

    date_str = datetime_str.strftime("%Y-%m-%d")
    hour_str = datetime_str.strftime("%H")
    minute_str = datetime_str.strftime("%M")
    second_str = datetime_str.strftime("%S") if "%S" in fmt else "NA"

    user_match = re.search(r"DTAA/([A-Z0-9]+)", line)
    pc_match = re.search(r"PC-(\d+)", line)
    activity = parts[-1]

    return f"<DATE:{date_str}> <HOUR:{hour_str}> <MINUTE:{minute_str}> <SECOND:{second_str}> USER:{user_match.group(1) if user_match else 'NA'} PC:{pc_match.group(1) if pc_match else 'NA'} {activity}"

normalized_logs = [log for log in (parse_log(l) for l in log_data) if log]

for log in normalized_logs:
    print(log)
