# %%
import torch
import torch.nn as nn
from torch.nn import functional
from torch.utils.data import Dataset as torchDataset, DataLoader
from tqdm.auto import tqdm
from classes.Transformers import ByteTokenizer, Transformer

# %%
cuda = torch.cuda.is_available()
print(cuda, torch.cuda.get_device_name())

# %%
batch_size = 32
context = 256
emb_dims = 128
print_interval = 500
device = 'cuda' if cuda else 'cpu'
max_iters = 5000
epochs = 10


# %%
# Reading the file
file = open('input.txt', 'r', encoding='utf-8')
text = file.read()

# %%
# here are all the unique characters that occur in this text
chars = sorted(list(set(text)))
vocab_size = len(chars)

# %%
tokenizer = ByteTokenizer(chars)

# %%
class Dataset(torchDataset):
    def __init__(self, text: str) -> None:
      self.data = tokenizer.encode(text)

    def __getitem__(self, index):
      x = self.data[index : index + context]
      y = self.data[index + 1 : index + context + 1]

      return torch.tensor(x).to(device), torch.tensor(y).to(device)
    def __len__(self):
      return len(self.data) - context - 1

# %%
dataset = Dataset(text=text)
print(len(dataset))

# %%
dataloader = DataLoader(dataset=dataset, batch_size=batch_size, shuffle=True)

# %%
model = Transformer(context=context, emb_dims=emb_dims, vocab_size=vocab_size).to(device=device)

# Print the number of parameters in the model
print(sum(param.numel() for param in model.parameters()) / 1e6, 'M parameters')

# Create a PyTorch optimizer
optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)

# %%
# Training loop

progress_bar = tqdm(range(epochs * len(dataloader)))

for epoch in range(epochs):
    total_loss = 0
    for step, batch in enumerate(dataloader):
        # every once in a while evaluate the loss on train and val sets
        if step % print_interval == 0 :
            tqdm.write(f"step {step}: train loss {total_loss / (step + 1)}")

        x, y = batch
        # evaluate the loss
        logits, loss = model.forward(x = x, targets =y)
        total_loss += loss.item()
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        progress_bar.update(1)


torch.save(model.state_dict(), 'makemore.pt')
# %%
# Generate data
start = torch.zeros((1, 1), dtype=torch.long, device=device)
open('more.txt', 'w').write(tokenizer.decode(model.generate(start, max_new_tokens=10000)[0].tolist()))

