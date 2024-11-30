# -*- coding: utf-8 -*-
"""Untitled1.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1c0q9EKo-8UttR_8WyVsws_6o2cmMlIXB
"""

import copy
import torch
import torchvision
import torchvision.transforms as transforms
import numpy as np
from torch.utils.data import random_split, DataLoader
import torch.nn.functional as F
import torch.nn as nn

# Set device (CPU or GPU)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Malicious Client Simulation Function
def simulate_malicious_client(model):
    for param in model.parameters():
        param.data = torch.randn_like(param)
    return model

# Detection Function (Detects deviations from the global model)
def detect_malicious_updates(global_model, local_parameters, threshold=1.0):
    malicious_clients = []
    global_params = global_model.state_dict()
    deviations = []

    for idx, params in enumerate(local_parameters):
        diff = sum(torch.sum((params[key] - global_params[key]) ** 2).item() for key in params)
        distance = torch.sqrt(torch.tensor(diff))
        deviations.append(distance.item())

    max_deviation_idx = np.argmax(deviations)
    if deviations[max_deviation_idx] > threshold:
        malicious_clients.append(max_deviation_idx)

    return malicious_clients

class EqualUserSampler:
    def __init__(self, n, num_users):
        self.i = 0
        self.selected = n
        self.num_users = num_users
        self.get_order()

    def get_order(self):
        self.users = np.arange(self.num_users)

    def get_useridx(self):
        selection = []
        for _ in range(self.selected):
            selection.append(self.users[self.i])
            self.i += 1
            if self.i >= self.num_users:
                self.get_order()
                self.i = 0
        return selection

# Load data
def load_data(transform, datasets='MNIST'):
    if datasets == 'MNIST':
        train_dataset = torchvision.datasets.MNIST(
            root="./data/mnist", train=True, download=True, transform=transform
        )
        test_dataset = torchvision.datasets.MNIST(
            root="./data/mnist", train=False, download=True, transform=transform
        )
    return train_dataset, test_dataset

# Partition the dataset into 'n_clients' partitions
def partition_dataset(dataset, n_clients):
    split_size = len(dataset) // n_clients
    return random_split(dataset, [split_size] * n_clients)

# CNN Model Definition
class ConvNet(nn.Module):
    def __init__(self):
        super(ConvNet, self).__init__()
        self.conv1 = nn.Conv2d(1, 32, 3)  # 32 filters
        self.conv2 = nn.Conv2d(32, 64, 3)  # 64 filters
        self.pool = nn.MaxPool2d(2, 2)
        self.fc1 = nn.Linear(64 * 5 * 5, 128)  # Adjust for MNIST dimensions
        self.fc2 = nn.Linear(128, 10)
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(0.5)

    def forward(self, x):
        x = self.pool(self.relu(self.conv1(x)))
        x = self.pool(self.relu(self.conv2(x)))
        x = x.view(x.size(0), -1)  # Dynamic flatten
        x = self.relu(self.fc1(x))
        x = self.dropout(x)
        x = self.fc2(x)
        return x

class FedAvgServer:
    def __init__(self, global_parameters):
        self.global_parameters = global_parameters

    def download(self, user_idx):
        local_parameters = [copy.deepcopy(self.global_parameters) for _ in user_idx]
        return local_parameters

    def upload(self, local_parameters):
        for k, v in self.global_parameters.items():
            tmp_v = torch.zeros_like(v)
            for params in local_parameters:
                tmp_v += params[k]
            self.global_parameters[k] = tmp_v / len(local_parameters)

class Client:
    def __init__(self, data_loader):
        self.data_loader = data_loader

    def train(self, model, learning_rate, epochs):
        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
        scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=5, gamma=0.7)
        model.to(device)
        model.train()
        for _ in range(epochs):
            for data, labels in self.data_loader:
                data, labels = data.to(device), labels.to(device)
                optimizer.zero_grad()
                output = model(data)
                loss = F.cross_entropy(output, labels)
                loss.backward()
                optimizer.step()
            scheduler.step()

# Training Function
def train(train_dataloaders, user_idx, server, global_model, learning_rate, epochs, malicious_idx=None):
    clients = [Client(train_dataloaders[idx]) for idx in user_idx]
    local_parameters = []

    for i, client in enumerate(clients):
        model = ConvNet().to(device)
        model.load_state_dict(server.global_parameters)

        if i == malicious_idx:
            model = simulate_malicious_client(model)

        client.train(model, learning_rate, epochs)
        local_parameters.append(model.state_dict())

    server.upload(local_parameters)
    global_model.load_state_dict(server.global_parameters)
    return local_parameters

# Test Function
def test(model, test_loader):
    model.eval()
    correct, total = 0, 0
    with torch.no_grad():
        for data, labels in test_loader:
            data, labels = data.to(device), labels.to(device)
            outputs = model(data)
            _, predicted = torch.max(outputs, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()
    return 100 * correct / total

# Main Training Process with Model Saving
def train_main(n_clients=10, save_path='global_model.pth'):
    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.5,), (0.5,))
    ])

    global_model = ConvNet().to(device)
    global_parameters = global_model.state_dict()
    server = FedAvgServer(global_parameters)

    train_dataset, test_dataset = load_data(transform)
    client_datasets = partition_dataset(train_dataset, n_clients)
    client_loaders = [DataLoader(dataset, batch_size=50, shuffle=True, num_workers=2) for dataset in client_datasets]
    test_loader = DataLoader(test_dataset, batch_size=1000, shuffle=False)

    sampler = EqualUserSampler(n_clients, n_clients)
    malicious_idx = 1

    for epoch in range(1, 21):  # 20 epochs for better training
        print(f"Global Epoch {epoch}/20")
        user_idx = sampler.get_useridx()
        local_parameters = train(client_loaders, user_idx, server, global_model, 0.001, 3, malicious_idx)
        test_acc = test(global_model, test_loader)
        print(f"Global Model Test Accuracy after round {epoch}: {test_acc:.2f}")
        malicious_clients = detect_malicious_updates(global_model, local_parameters)
        print(f"Malicious clients detected: {malicious_clients}")

        # Save model if accuracy exceeds 90%

        torch.save(global_model.state_dict(), save_path)
        print(f"Model saved to {save_path} with accuracy: {test_acc:.2f}")

if __name__ == '__main__':
    train_main()