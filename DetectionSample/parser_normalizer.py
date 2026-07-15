from kafka import KafkaConsumer, KafkaProducer
from datetime import datetime
from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig
from drain3.file_persistence import FilePersistence
import json

consumer = KafkaConsumer(
    "raw_logs",
    bootstrap_servers="localhost:9092",
    auto_offset_reset="earliest",
    group_id="parser-group",
    value_deserializer=lambda x: x.decode('utf-8')
)

producer = KafkaProducer(
    bootstrap_servers="localhost:9092",
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

normalized_topic = "normalized_logs"
config = TemplateMinerConfig()
persistence = FilePersistence("drain3_state.bin")
template_miner = TemplateMiner(persistence, config)

date_formats = [
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M"
]

def parse_log(line):

    try:
        parts = line.strip().split("\t")
        if len(parts) != 5:
            return None

        log_id, datetime_str, user, pc, activity = parts


        dt = None
        for fmt in date_formats:
            try:
                dt = datetime.strptime(datetime_str, fmt)
                break
            except ValueError:
                continue
        if not dt:
            return None


        date_str = dt.strftime("%Y-%m-%d")
        hour_str = dt.strftime("%H")
        minute_str = dt.strftime("%M")
        second_str = dt.strftime("%S")


        template_miner.add_log_message(line)


        normalized_log = {
            "DATE": date_str,
            "HOUR": hour_str,
            "MINUTE": minute_str,
            "SECOND": second_str,
            "USER": user.split("/")[-1] if "/" in user else user,
            "PC": pc.replace("PC-", ""),
            "ACTIVITY": activity,
            "RAW_LOG": line
        }

        return normalized_log
    except Exception as e:
        print(f"[ERROR] Failed to parse log: {e}")
        return None

output_file = open("normalized_logs.txt", "w")

print("Listening for raw logs...")
try:
    for message in consumer:
        log_line = message.value
        normalized = parse_log(log_line)

        if normalized:
            print(f"Normalized: {normalized}")

            output_file.write(json.dumps(normalized) + "\n")
            output_file.flush()


            producer.send(normalized_topic, value=normalized)
            producer.flush()
except KeyboardInterrupt:
    print("Stopping parser...")
finally:
    output_file.close()
    producer.close()
    consumer.close()
