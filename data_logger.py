import csv
from datetime import datetime

class CSVLogger:
    def __init__(self, filename, fieldnames):
        self.filename = filename
        self.fieldnames = fieldnames
        self.data = {field: None for field in fieldnames}
        
        # Create the CSV file and write the header
        with open(self.filename, 'w', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=self.fieldnames)
            writer.writeheader()
    
    def update_properties(self, **kwargs):
        for key, value in kwargs.items():
            if key in self.data:
                self.data[key] = value

    def update_property(self, key, value):
        self.data[key] = value
        self.data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def log_to_csv(self):
        with open(self.filename, 'a', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=self.fieldnames)
            writer.writerow(self.data)