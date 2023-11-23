import json
import base64
import helper
import config

BASE_TOKENS = 1000

DEFAULT_NUM_IMAGES = 1

INFERENCE_ENDPOINT = "https://api.getimg.ai/v1/stable-diffusion/text-to-image"
XL_INFERENCE_ENDPOINT = "https://api.getimg.ai/v1/stable-diffusion-xl/text-to-image"
UPSCALE_ENDPOINT = "https://api.getimg.ai/v1/enhancements/upscale"

COMMON_INPUTS = {
    "output_format": "jpeg",
}

# dummy function for localization
def _(text):
    return text

TIPS = [ 
    _("The price is for 1 image"),
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
    "real": {
        "name": _("Photorealistic"),
        "model_id": "absolute-reality-v1-8-1",
        "tips": TIPS,
        "size_options": SIZE_OPTIONS,
        "inputs": {
            "negative_prompt": "BadDream, (UnrealisticDream:1.3)",
            "steps": 30,
            "guidance": 9,
            "scheduler": "dpmsolver++",
        }
    },
    "unreal": {
        "name": _("Unreal (2.5D)"),
        "model_id": "dream-shaper-v8",
        "tips": TIPS,
        "size_options": SIZE_OPTIONS,
        "inputs": {
            "negative_prompt": "disfigured, kitsch, ugly, oversaturated, grain, low-res, Deformed, blurry, bad anatomy, disfigured, poorly drawn face, mutation, mutated, extra limb, ugly, poorly drawn hands, missing limb, blurry, floating limbs, disconnected limbs, malformed hands, blur, out of focus, long neck, long body, ugly, disgusting, poorly drawn, childish, mutilated, mangled, old, surreal, calligraphy, sign, writing, watermark, text, body out of frame, extra legs, extra arms, extra feet, out of frame, poorly drawn feet, cross-eye, blurry, bad anatomy",
            "steps": 20,
            "guidance": 7,
            "scheduler": "dpmsolver++",
        }
    },
    "dark": {
        "name": _("Anime"),
        "model_id": "dark-sushi-mix-v2-25",
        "tips": TIPS,
        "size_options": SIZE_OPTIONS,
        "inputs": {
            "negative_prompt": "paintings, sketches, fingers, (worst quality:2), (low quality:2), (normal quality:2), lowres, normal quality, ((monochrome)), ((grayscale)), skin spots, acnes, skin blemishes, age spot, (outdoor:1.6), backlight,(ugly:1.331), (duplicate:1.331), (morbid:1.21), (mutilated:1.21), (tranny:1.331), mutated hands, (poorly drawn hands:1.5), blurry, (bad anatomy:1.21), (bad proportions:1.331), extra limbs, (disfigured:1.331), (more than 2 nipples:1.331), (missing arms:1.331), (extra legs:1.331), (fused fingers:1.61051), (too many fingers:1.61051), (unclear eyes:1.331), lowers, bad hands, missing fingers, extra digit, (futa:1.1),bad hands, missing fingers, bad-hands-5",
            "steps": 20,
            "guidance": 8,
            "scheduler": "dpmsolver++",
        }
    },
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

async def _api(endpoint, data):
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": f"Bearer {config.GETIMG_API_TOKEN}"
    }

    return await helper.http_post(endpoint, json.dumps(data), headers=headers)

async def upscale(image):
    encoded_image_bytes = base64.b64encode(image)
    base64_string = encoded_image_bytes.decode("utf-8")
    data = {
        "image": base64_string,
        "model": "real-esrgan-4x",
        # Currently only supports scale 4x
        "scale": 4, 
        "output_format": "jpeg"
    }
    result = await _api(UPSCALE_ENDPOINT, data)
    image = None
    if "image" in result:
        image = base64.b64decode(result["image"])
        print("upscale cost: {}".format(result["cost"]))
    return image

async def inference(model, width, height, prompt):
    if model not in MODELS:
        print(f"invalid model: {model}")
        return None        
    
    m = MODELS[model]
    inputs = m["inputs"]
    
    data = {
        **COMMON_INPUTS,
        "model": m["model_id"],
        **inputs,
        "width": width,
        "height": height,
        "prompt": prompt,
    }

    endpoint = m["endpoint"] if "endpoint" in m else INFERENCE_ENDPOINT
    result = await _api(endpoint, data)
    if "image" in result:
        print("cost: {}".format(result["cost"]))
        generated_image_data = base64.b64decode(result["image"])
        image_data = {"image": generated_image_data}
        if "seed" in result:
            image_data["seed"] = result["seed"]
        return [image_data]
    error = result["error"]
    error_msg = "Error: {}, {}".format(error["code"], error["message"])
    print(error_msg)
    raise Exception(error_msg)

populate_costs(MODELS)