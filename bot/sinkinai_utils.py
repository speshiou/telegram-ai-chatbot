import helper
import config

BASE_TOKENS = 1600

DEFAULT_NUM_IMAGES = 2

INFERENCE_ENDPOINT = "https://sinkin.ai/m/inference"
LORA_DETAILER_ID = "647944c3911a6fa8a2e2712b"

BASE_FORM_DATA = {
    "user_email": config.SINKIN_ACCOUNT,
    "num_images": DEFAULT_NUM_IMAGES,
    "seed": "-1",
    "scheduler": "K_EULER_ANCESTRAL",
    "lora": "none",
    "lora_scale": "0.75"
}

# dummy function for localization
def _(text):
    return text

TIPS = [ 
    _("The price is for 2 images"),
    _("Use English prompt to get better results"),
]

SIZE_OPTIONS = [
    {
        "width": 512,
        "height": 512,
    },
    {
        "width": 512,
        "height": 768,
    },
    {
        "width": 768,
        "height": 512,
    },
]

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

# keep model key short to prevent callback_data from exceeding size limit
MODELS = {
    # "real": {
    #     "name": _("Photorealistic"),
    #     "model_id": "mGYMaD5",
    #     "tips": TIPS,
    #     "size_options": SIZE_OPTIONS,
    #     "inputs": {
    #         "version": "1.6",
    #         "negative_prompt": "BadDream, (cgi render, 3d, cartoon, drawing, low quality, worst quality:1.2)",
    #         "steps": 30,
    #         "scale": "7.5",
    #         "scheduler": "DPMSolverMultistep",
    #         "use_default_neg": "false",
    #     }
    # },
    # "dream": {
    #     "name": _("Unreal (2.5D)"),
    #     "model_id": "4zdwGOB",
    #     "tips": TIPS,
    #     "size_options": SIZE_OPTIONS,
    #     "inputs": {
    #         "version": "8",
    #         "prompt_template": "best quality, highly detailed, intricate, {}",
    #         "steps": 20,
    #         "scale": "7",
    #         "scheduler": "DPMSolverMultistep",
    #         "use_default_neg": "true",
    #         "lora": LORA_DETAILER_ID, 
    #         "lora_scale": "0.5",
    #     }
    # },
    # "meina": {
    #     "name": _("Anime"),
    #     "model_id": "vln8Nwr",
    #     "tips": TIPS,
    #     "size_options": SIZE_OPTIONS,
    #     "inputs": {
    #         "version": "11",
    #         "negative_prompt": "(worst quality, low quality:1.4), (zombie, sketch, interlocked fingers, comic),",
    #         "steps": 20,
    #         "scale": "7",
    #         "scheduler": "K_EULER_ANCESTRAL",
    #         "use_default_neg": "false",
    #         "lora": LORA_DETAILER_ID, 
    #         "lora_scale": "0.3",
    #     }
    # },
}

def populate_costs(models):
    for key, m in models.items():
        steps = m["inputs"]["steps"]
        for size in m["size_options"]:
            width = size["width"]
            height = size["height"]
            cost = calc_credit_cost(width, height, steps=steps, num_images=DEFAULT_NUM_IMAGES) * BASE_TOKENS
            size["cost"] = int(cost)

def calc_credit_cost(width: int, height: int, steps: int, num_images=DEFAULT_NUM_IMAGES):
    base_time = 3

    num_images_factor = num_images
    steps_factor = steps / 30
    w_factor = width / 512
    h_factor = height / 512

    gen_time = base_time + num_images_factor * steps_factor * w_factor * h_factor

    credit_cost = gen_time / 2

    return round(credit_cost * 10) / 10    # round to 1 decimal place

async def inference(model, width, height, prompt):
    if model not in MODELS:
        print(f"invalid model: {model}")
        return None        
    
    m = MODELS[model]
    inputs = m["inputs"]
    steps = inputs["steps"]
    estimated_credit = calc_credit_cost(width, height, steps, DEFAULT_NUM_IMAGES)
    print(f"estimated credit={estimated_credit}")
    
    if "prompt_template" in inputs:
        prompt = inputs["prompt_template"].format(prompt)
    data = {
        **BASE_FORM_DATA,
        "model_id": m["model_id"],
        **inputs,
        "width": width,
        "height": height,
        "prompt": prompt,
    }

    result = await helper.http_post(INFERENCE_ENDPOINT, data)
    feed = None
    if "feed" in result:
        feed = result["feed"]
    elif "images" in result:
        feed = result
    if feed is not None and "images" in feed:
        print("credit_cost: {}".format(feed["credit_cost"]))
        return feed["images"]
    print("Error: {}, {}".format(result["error_code"], result["message"]))
    raise Exception("Error code: {}".format(result["error_code"]))

populate_costs(MODELS)