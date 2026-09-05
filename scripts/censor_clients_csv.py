import pandas as pd

clients = pd.read_csv("data/clients.csv")

clients_uncensored = clients[["client_id", "client_name", "age"]]

clients_censored = clients.drop(columns=["client_name"])

bins = [0, 18, *range(25, 101, 5), float("inf")]
labels = ["0-17", "18-24"] + [f"{i}-{i+4}" for i in range(25, 100, 5)] + ["100+"]

clients_censored["age_range"] = pd.cut(clients["age"], bins=bins, labels=labels, right=True)

clients_censored = clients_censored.drop(columns=["age"])

clients_uncensored.to_csv("data/clients_uncensored.csv", index=False)
clients_censored.to_csv("data/clients_censored.csv", index=False)
