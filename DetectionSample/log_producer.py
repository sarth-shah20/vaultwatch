from kafka import KafkaProducer

producer = KafkaProducer(bootstrap_servers='localhost:9092')
topic_name = "raw_logs"

with open("sample_logs.csv", "r") as file:
    for line in file:
        log = line.strip()
        if log:
            producer.send(topic_name, value=log.encode('utf-8'))
            print(f"Sent: {log}")

producer.flush()
print("All logs sent to Kafka topic:", topic_name)

