# Initialize Phi-3.5-mini and Llama-2-13B models from Hugging Face

from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

# Configuration
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
DTYPE = torch.float16 if torch.cuda.is_available() else torch.float32

def initialize_phi_3_5_mini():
    print("Loading Phi-3.5-mini")
    
    model_name = "microsoft/Phi-3.5-mini-instruct"
    
    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        trust_remote_code=True
    )
    
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=DTYPE,
        device_map=DEVICE,
        trust_remote_code=True
    )
    
    print(f"Phi-3.5-mini loaded")
    return model, tokenizer


def initialize_llama_2_13b():
    print("Loading Llama-2-13B")
    
    model_name = "meta-llama/Llama-2-13b-hf"
    
    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        trust_remote_code=True
    )
    
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=DTYPE,
        device_map=DEVICE,
        trust_remote_code=True
    )
    
    print(f"Llama-2-13B loaded")
    return model, tokenizer


def main():
    print(f"Initializing models on device: {DEVICE}\n")
    
    # Initialize models
    phi_model, phi_tokenizer = initialize_phi_3_5_mini()
    llama_model, llama_tokenizer = initialize_llama_2_13b()

    
    # Return models
    return {
        "phi": {"model": phi_model, "tokenizer": phi_tokenizer},
        "llama": {"model": llama_model, "tokenizer": llama_tokenizer}
    }


if __name__ == "__main__":
    models = main()
