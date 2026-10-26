import sys
from kombu import Connection

def clear_queue():
    broker_url = 'amqp://guest:guest@127.0.0.1:5672//'
    try:
        with Connection(broker_url) as conn:
            channel = conn.channel()
            # Try to delete the queue explicitly
            channel.queue_delete(queue='progress_updates')
            print("Successfully deleted the 'progress_updates' queue from RabbitMQ!")
    except Exception as e:
        print(f"Error deleting queue: {e}")

if __name__ == "__main__":
    clear_queue()
