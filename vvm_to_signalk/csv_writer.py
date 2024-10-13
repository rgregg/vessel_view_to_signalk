"""Outputs data in CSV format to storage"""
import csv
import threading
from datetime import datetime

class CSVWriter:
    """Outputs data in CSV format to storage"""
    def __init__(self, filename, fieldnames):
        self.filename = filename
        self.fieldnames = fieldnames
        self.data = {field: None for field in fieldnames}
        self.timer = None
        
        # Create the CSV file and write the header
        with open(self.filename, 'a', newline='', encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=self.fieldnames)
            writer.writeheader()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.log_to_csv()
    
    def update_properties(self, **kwargs):
        """Update properties in the CSV output"""
        for key, value in kwargs.items():
            if key in self.data:
                self.data[key] = value

    def update_property(self, key, value):
        """Update properties in the CSV output"""
        self.data[key] = value
        self.data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self.timer is None:
            self.timer = threading.Timer(1.0, self.log_to_csv)
            self.timer.start()
    
    def log_to_csv(self):
        """Open the output file and create a writer"""
        with open(self.filename, 'a', newline='', encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=self.fieldnames)
            writer.writerow(self.data)
        self.timer = None