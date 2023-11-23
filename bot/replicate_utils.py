import replicate

BASE_COST = 1000
DEFAULT_NUM_IMAGES = 1

# dummy function for localization
def _(text):
    return text

XL_SIZE_OPTIONS = [
    {
        "width": 1024,
        "height": 1024,
    },
    {
        "width": 768,
        "height": 1024,
    },
    {
        "width": 1024,
        "height": 768,
    },
]

TIPS = [ 
    _("The price is for 1 image"),
    _("Use English prompt to get better results"),
]

MODELS = {
    "sdxl": {
        "name": "Stable Diffusion XL",
        "model_id": "stability-ai/sdxl:c221b2b8ef527988fb59bf24a8b97c4561f1c671f73bd389f866bfb27c061316",
        "tips": TIPS,
        "size_options": XL_SIZE_OPTIONS,
        "inputs": {
            "num_outputs": 1,
            "scheduler": "K_EULER",
            "num_inference_steps": 25,
            "guidance_scale": 7.5,
            "prompt_strength": 0.8,
            "refine": "expert_ensemble_refiner",
            "high_noise_frac": 0.8,
            "apply_watermark": False,
        },
    }
}

def populate_costs(models):
    for key, m in models.items():
        steps = m["inputs"]["num_inference_steps"]
        for size in m["size_options"]:
            width = size["width"]
            height = size["height"]
            cost = calc_credit_cost(width, height, steps) * BASE_COST
            size["cost"] = int(cost)

def calc_credit_cost(width: int, height: int, steps: int, num_images=DEFAULT_NUM_IMAGES):
    base_time = 3

    num_images_factor = num_images
    steps_factor = steps / 30
    w_factor = width / 512
    h_factor = height / 512

    gen_time = base_time + num_images_factor * steps_factor * w_factor * h_factor

    credit_cost = gen_time / 2

    return round(credit_cost * 10) / 10

async def inference(model, prompt, width, height):
    if model not in MODELS:
        return None
    
    m = MODELS[model]
    results = replicate.run(
        m["model_id"],
        input={
            **m["inputs"],
            "prompt": prompt,
            "width": width,
            "height": height,
        }
    )
    print(results)
    return results

populate_costs(MODELS)