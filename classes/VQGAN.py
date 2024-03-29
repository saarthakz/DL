import torch
from torch import nn
import torch.nn.functional as func

class GroupNorm(nn.Module):
    def __init__(self, channels: int) -> None:
        super().__init__()
        
        self.group_norm = nn.GroupNorm(
            num_channels=channels,
            num_groups=32,
            eps=1e-6
        )

    def forward(self, x):
        return self.group_norm.forward(x)
    
class Swish(nn.Module):
    def __init__(self) -> None:
        super().__init__()

    def forward(self, x):
        return x * torch.sigmoid(x)
    
class ResBlock(nn.Module):
    def __init__(self, in_channels: int, out_channels: int) -> None:
        super().__init__()
        self.in_channels = in_channels
        self.out_channels = out_channels
        self.net = nn.Sequential(
            GroupNorm(in_channels),
            Swish(),
            nn.Conv2d(in_channels=in_channels, out_channels=out_channels, kernel_size=(3,3), stride=1, padding=1), # This Conv2D does not change the shape of the input, only the channels
            GroupNorm(out_channels),
            Swish(),
            nn.Conv2d(in_channels=out_channels, out_channels=out_channels, kernel_size=(3, 3), stride=1, padding=1) # This Conv2D does not change the shape of the input, including the channels. Try using the Conv Attention Block here instead
        )

        if in_channels != out_channels:
            self.channel_match = nn.Conv2d(in_channels=in_channels, out_channels=out_channels, kernel_size=(1, 1), stride=1, padding=0) # Used for channel matching the 'residual' input

    def forward(self, x):
        if self.in_channels != self.out_channels:
            return self.channel_match(x) + self.net(x)
        else:
            return x + self.net(x)
    
class UpSample(nn.Module):
    def __init__(self, channels: int) -> None:
        super().__init__()
        self.upsample = nn.ConvTranspose2d(
            in_channels=channels,
            out_channels=channels,
            kernel_size=(4, 4),
            stride=2,
            padding=1
        )

    def forward(self, x):
        return self.upsample(x)
    
class DownSample(nn.Module):
    def __init__(self, channels: int) -> None:
        super().__init__()
        self.down_sample = nn.Conv2d(
            in_channels=channels,
            out_channels=channels,
            kernel_size=(3,3),
            stride=2,
            padding=1
        )

    def forward(self, x):
        return self.down_sample(x)
    
class ConvAttention(nn.Module):
    def __init__(self, channels: int) -> None:
        super().__init__()

        self.in_channels = channels

        self.group_norm = GroupNorm(channels=channels)

        self.query = nn.Conv2d(in_channels=channels, out_channels=channels, kernel_size=(1,1), stride=1, padding=0)
        self.key = nn.Conv2d(in_channels=channels, out_channels=channels, kernel_size=(1,1), stride=1, padding=0)
        self.value = nn.Conv2d(in_channels=channels, out_channels=channels, kernel_size=(1,1), stride=1, padding=0)

        self.proj = nn.Conv2d(in_channels=channels, out_channels=channels, kernel_size=(1,1), stride=1, padding=0)

    def forward(self, x):
        gn_x = self.group_norm(x)

        B, C, H, W = gn_x.shape

        gn_x.permute(0, 2, 3, 1)

        query = self.query(gn_x).reshape(B, C, H*W)
        key = self.key(gn_x).reshape(B, C, H*W)
        value = self.value(gn_x).reshape(B, C, H*W)


        attn_score =  query @ key.transpose(-2, -1) * C ** -0.5
        # compute attention scores ("affinities")

        attn_score = func.softmax(attn_score, dim=-1) # (B, C, C)

        attn_score = attn_score @ value
        
        attn_score = attn_score.permute(0, 2, 1).reshape(B, C, H, W)
        return x + attn_score

# Encoder as implemented in the original VQGAN Paper
class Encoder(nn.Module):
    def __init__(self, args) -> None:
        super().__init__()

        channels = args.channels

        layers = [nn.Conv2d(in_channels=args.image_channels, out_channels=channels[0], kernel_size=(3,3), stride=1, padding=1)] # Same size, only number of channels changed

        for idx in range(len(channels) - 1):
            in_channels = channels[idx]    
            out_channels = channels[idx+1]
            layers.append(nn.Sequential(
                ResBlock(in_channels=in_channels, out_channels=out_channels),
                DownSample(channels=out_channels)
            )) 

        layers.append(ResBlock(in_channels=channels[-1], out_channels=channels[-1]))  

        layers.append(ConvAttention(channels=channels[-1]))  

        layers.append(ResBlock(in_channels=channels[-1], out_channels=channels[-1])) 

        layers.append(GroupNorm(channels=channels[-1]))

        layers.append(Swish())

        layers.append(nn.Conv2d(in_channels=channels[-1], out_channels=args.latent_dim, kernel_size=(3,3), stride=1, padding=1)) 

        self.model = nn.Sequential(*layers)

    def forward(self, x):
        return self.model(x)

# Decoder as implemented in the original VQGAN Paper
class Decoder(nn.Module):
    def __init__(self, args) -> None:
        super().__init__()

        channels = args.channels
        channels.reverse()

        layers = [nn.Conv2d(in_channels=args.latent_dim, out_channels=channels[0], kernel_size=(3,3), stride=1, padding=1)] 

        layers.append(ResBlock(in_channels=channels[0], out_channels=channels[0]))  

        layers.append(ConvAttention(channels=channels[0]))  

        layers.append(ResBlock(in_channels=channels[0], out_channels=channels[0])) 

        for idx in range(len(channels) - 1):
            in_channels = channels[idx]    
            out_channels = channels[idx+1]
            layers.append(nn.Sequential(
                ResBlock(in_channels=in_channels, out_channels=out_channels),
                UpSample(channels=out_channels)
            )) 

        layers.append(GroupNorm(channels=channels[-1]))

        layers.append(Swish())

        layers.append(nn.Conv2d(in_channels=channels[-1], out_channels=args.image_channels, kernel_size=(3,3), stride=1, padding=1)) 

        self.model = nn.Sequential(*layers)

    def forward(self, x):
        return self.model(x)

class VectorQuantizer(nn.Module):
    def __init__(self, args) -> None:
        super().__init__()
        self.num_embeddings = args.num_embeddings
        self.latent_dim = args.latent_dim
        self.beta = args.beta # Beta is a weighting factor for the "codebook gradient flowing" loss also called the commitment cost

        self.embedding = nn.Embedding(num_embeddings=self.num_embeddings, embedding_dim=self.latent_dim)
        self.embedding.weight.data.uniform_(-1.0 / self.num_embeddings, 1.0 / self.num_embeddings) # Uniform data initialization for the codebook vectors

    def forward(self, z):
        # z is B, C, H, W
        z = z.permute(0, 2, 3, 1).contiguous() # Contigous method used for memory arrangement
        z_flat = z.view(-1, self.latent_dim) # (B * H * W, C)

        dis = torch.sum(z_flat**2, dim=1, keepdim=True) + torch.sum(self.embedding.weight**2, dim=1) - 2*(torch.matmul(z_flat, self.embedding.weight.t())) # Calculating the distances of the encoded vectors to the codebook vectors

        min_encoding_indices = torch.argmin(dis, dim=1) # Getting the indices of the min distant vector for each input
        z_q = self.embedding(min_encoding_indices).view(z.shape) # Getting the codebook vectors

        loss = torch.mean((z_q.detach() - z)**2) + self.beta * torch.mean((z_q - z.detach())**2)

        z_q = z + (z_q - z).detach() # For preserving the gradients for backprop

        z_q = z_q.permute(0, 3, 1, 2) # (B, C, H, W)

        return z_q, min_encoding_indices, loss
    
# Generator for the VQGAN
class VQGAN(nn.Module):
    def __init__(self, args) -> None:
        super().__init__()
        self.encoder = Encoder(args).to(device=args.device)
        self.decoder = Decoder(args).to(device=args.device)
        self.codebook = VectorQuantizer(args).to(device=args.device)  

        # Defined in the VQGAN Architecture
        self.pre_quant_conv = nn.Conv2d(in_channels=args.latent_dim, out_channels=args.latent_dim, kernel_size=(1,1), stride=1, padding=0).to(device=args.device)

        # Defined in the VQGAN Architecture
        self.post_quant_conv = nn.Conv2d(in_channels=args.latent_dim, out_channels=args.latent_dim, kernel_size=(1,1), stride=1, padding=0).to(device=args.device) 

    def encode(self, x):
        encoded = self.encoder(x)
        pre_quant_encoded = self.pre_quant_conv(encoded)
        return pre_quant_encoded
        
    def through_codebook(self, pre_quant_encoded):
        codebook_mapping, codebook_indices, q_loss = self.codebook(pre_quant_encoded)
        return codebook_mapping, codebook_indices, q_loss

    def decode(self, z):
        post_quant_encoded = self.post_quant_conv(z)
        decoded = self.decoder(post_quant_encoded)
        return decoded

    # Combining the Encoder, Codebook and Decoder methods
    def forward(self, x):
        pre_quant_encoded = self.encode(x)
        codebook_mapping, codebook_indices, q_loss = self.through_codebook(pre_quant_encoded)
        decoded = self.decode(codebook_mapping)

        return decoded, codebook_indices, q_loss
    
    def load_checkpoint(self, path):
        self.load_state_dict(torch.load(path))

# Discriminator for the VQGAN
class Discriminator(nn.Module):
    def __init__(self, args, num_filters_last=64, n_layers=3):
        super(Discriminator, self).__init__()

        layers = [nn.Conv2d(args.image_channels, num_filters_last, 4, 2, 1), nn.LeakyReLU(0.2)]
        num_filters_mult = 1

        for i in range(1, n_layers + 1):
            num_filters_mult_last = num_filters_mult
            num_filters_mult = min(2 ** i, 8)
            layers += [
                nn.Conv2d(num_filters_last * num_filters_mult_last, num_filters_last * num_filters_mult, 4,
                          2 if i < n_layers else 1, 1, bias=False),
                nn.BatchNorm2d(num_filters_last * num_filters_mult),
                nn.LeakyReLU(0.2, True)
            ]

        layers.append(nn.Conv2d(num_filters_last * num_filters_mult, 1, 4, 1, 1))
        self.model = nn.Sequential(*layers)

    def forward(self, x):
        return self.model(x)