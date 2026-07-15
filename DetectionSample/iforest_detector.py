from kafka import KafkaConsumer
from sklearn.ensemble import IsolationForest
from sklearn.feature_extraction.text import TfidfVectorizer
import numpy as np
import json
import os

def save_results(anomalies, normal_count, anomalies_count, total_count, filename="anomaly_results.json"):
    data = {
        "total_logs": total_count,
        "normal_count": normal_count,
        "anomalies_count": anomalies_count,
        "anomaly_percentage": (anomalies_count / total_count) * 100 if total_count > 0 else 0,
        "anomalies": anomalies}
    with open(filename, "w") as f:
        json.dump(data, f, indent=4)

class iForestASD:
    def __init__(self, window_size=50, contamination=0.01, random_state=42):
        self.window_size = window_size
        self.contamination = contamination
        self.random_state = random_state
        self.vectorizer = TfidfVectorizer()
        self.model = None
        self.data_window_raw = []
        self.data_window_vectorized = None

    def add_logs(self, new_logs):
        self.data_window_raw.extend(new_logs)

        if len(self.data_window_raw) > self.window_size:
            self.data_window_raw = self.data_window_raw[-self.window_size:]

    def vectorize_logs(self):
        if len(self.data_window_raw) == 0:
            self.data_window_vectorized = None
            return
        self.data_window_vectorized = self.vectorizer.fit_transform(self.data_window_raw).toarray()

    def train(self):
        if self.data_window_vectorized is None or len(self.data_window_raw) < self.window_size:
            print(f"Waiting for {self.window_size - len(self.data_window_raw)} more logs to start training...")
            return False
        self.model = IsolationForest(contamination=self.contamination, random_state=self.random_state)
        self.model.fit(self.data_window_vectorized)
        return True

    def predict(self):
        if self.model is None:
            print("Model not trained yet.")
            return None, None
        predictions = self.model.predict(self.data_window_vectorized)  # -1 = anomaly, 1 = normal
        scores = self.model.decision_function(self.data_window_vectorized)
        return predictions, scores

    def explain_anomaly(self, idx, top_n=5):

        feature_names = np.array(self.vectorizer.get_feature_names_out())
        vector = self.data_window_vectorized[idx]
        top_indices = vector.argsort()[-top_n:][::-1]
        top_features = feature_names[top_indices]
        return ', '.join(top_features)

def read_logs_from_file(filename="normalized_logs.txt"):
    logs = []
    if os.path.exists(filename):
        with open(filename, "r") as f:
            for line in f:
                log_line = line.strip()
                if log_line:
                    logs.append(log_line)
    return logs

def main(use_kafka=True, kafka_topic="normalized_logs", kafka_bootstrap="localhost:9092"):
    detector = iForestASD(window_size=50, contamination=0.05, random_state=42)
    batch_logs = []

    if use_kafka:
        print("Starting Kafka consumer mode...")
        consumer = KafkaConsumer(
            kafka_topic,
            bootstrap_servers=kafka_bootstrap,
            auto_offset_reset="earliest",
            group_id="iforest-group",
            value_deserializer=lambda x: x.decode('utf-8')
        )

        print("Listening for logs from Kafka topic:", kafka_topic)
        for message in consumer:
            log_line = message.value.strip()
            print(f"Received log: {log_line}")
            batch_logs.append(log_line)

            if len(batch_logs) >= detector.window_size:
                process_batch(detector, batch_logs)
                batch_logs = []

    else:
        print("Reading logs from local file mode...")
        logs = read_logs_from_file()
        print(f"Total logs read from file: {len(logs)}")
        for i in range(0, len(logs), detector.window_size):
            batch = logs[i:i + detector.window_size]
            process_batch(detector, batch)

def process_batch(detector, batch_logs):
    detector.add_logs(batch_logs)
    detector.vectorize_logs()
    trained = detector.train()
    if not trained:
        return

    predictions, scores = detector.predict()
    if predictions is None:
        return

    anomalies_detected = 0
    total_logs = len(detector.data_window_raw)
    print("\n----- Anomaly Detection Results -----")
    anomaly_list = []
    for i, (log, pred, score) in enumerate(zip(detector.data_window_raw, predictions, scores)):
        if pred == -1:  # anomaly
            anomalies_detected += 1
            explanation = detector.explain_anomaly(i)
            print(f"[Anomaly] Score: {score:.4f}\nLog: {log}\nReason: This log contains unusual features: {explanation}\n")
            anomaly_list.append({
                "log": log,
                "score": float(score),
                "reason": f"This log contains unusual features: {explanation}"
            })

    normal_count = total_logs - anomalies_detected
    print("Batch Summary:")
    print(f"Total Logs Processed: {total_logs}")
    print(f"Anomalous Logs: {anomalies_detected} ({(anomalies_detected / total_logs) * 100:.2f}%)")
    print(f"Normal Logs: {normal_count} ({(normal_count / total_logs) * 100:.2f}%)\n")
    print("Waiting for next batch...\n")

    save_results(anomaly_list, normal_count, anomalies_detected, total_logs)

if __name__ == "__main__":

    main(use_kafka=True)
