import base64
import io
from contextlib import asynccontextmanager

import torch
from diffusers import StableDiffusionXLInpaintPipeline
from deep_translator import GoogleTranslator
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, HTTPException
from PIL import Image, ImageOps
from pydantic import BaseModel, Field


class RedrawRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    strength: float = Field(default=1.0, ge=0.0, le=1.0)
    guidance_scale: float = Field(default=10.0, ge=1.0, le=20.0)
    original_image: str
    mask_image: str


def base64_to_pil(base64_str: str) -> Image.Image:
    """
    将前端传入的 Base64 字符串解码为 PIL Image。
    兼容 data URL 形式（如 data:image/png;base64,xxxx）。
    """
    try:
        # 如果是 data URL，先截掉前缀只保留纯 Base64 内容
        if "," in base64_str:
            base64_str = base64_str.split(",", 1)[1]

        image_bytes = base64.b64decode(base64_str)
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        return image
    except Exception as exc:
        raise ValueError(f"Base64 转图片失败: {str(exc)}") from exc


def pil_to_base64(pil_image: Image.Image) -> str:
    """
    将 PIL Image 编码为 PNG 格式的 Base64 字符串（带 data URL 前缀）。
    """
    try:
        buffer = io.BytesIO()
        pil_image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{encoded}"
    except Exception as exc:
        raise ValueError(f"图片转 Base64 失败: {str(exc)}") from exc


def resize_with_padding(
    image: Image.Image,
    target_size: int,
    mode: str,
    background_color,
    resample,
) -> Image.Image:
    """
    以“同比例缩放 + 居中填充”的方式适配到目标分辨率，避免直接 resize 造成形变。
    """
    converted = image.convert(mode)
    contained = ImageOps.contain(converted, (target_size, target_size), method=resample)
    canvas = Image.new(mode, (target_size, target_size), background_color)
    paste_x = (target_size - contained.width) // 2
    paste_y = (target_size - contained.height) // 2
    canvas.paste(contained, (paste_x, paste_y))
    return canvas


def translate_to_english(text: str) -> str:
    """
    将任意语言文本翻译为英文，供文生图模型使用。
    若文本为空，直接返回空字符串；若翻译失败，抛出明确异常。
    """
    try:
        if not text or not text.strip():
            return ""
        translator = GoogleTranslator(source="auto", target="en")
        translated_text = translator.translate(text)
        if not translated_text or not translated_text.strip():
            raise ValueError("翻译结果为空")
        return translated_text
    except Exception as exc:
        raise ValueError(f"提示词翻译失败: {str(exc)}") from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    在 FastAPI 启动阶段加载 Inpainting 模型，避免每次请求重复加载。
    优先使用 CUDA + float16，提高推理速度并降低显存占用。
    """
    try:
        model_id = "diffusers/stable-diffusion-xl-1.0-inpainting-0.1"
        if not torch.cuda.is_available():
            raise RuntimeError("未检测到可用 CUDA GPU，当前仅配置了 GPU 推理。")

        app.state.pipe = StableDiffusionXLInpaintPipeline.from_pretrained(
            model_id,
            torch_dtype=torch.float16,
            variant="fp16",
        )
        # SDXL 必须启用 CPU Offload，避免高分辨率推理时显存溢出
        app.state.pipe.enable_model_cpu_offload()
        # 启用注意力切片，进一步降低显存峰值，减少 OOM 概率
        app.state.pipe.enable_attention_slicing()
        app.state.pipe_error = None
        print(f"Inpainting 模型加载完成: {model_id}")
    except Exception as exc:
        app.state.pipe = None
        app.state.pipe_error = str(exc)
        print(f"模型加载失败: {str(exc)}")
    yield
    # 服务关闭时主动释放模型与 CUDA 缓存，避免显存残留
    if getattr(app.state, "pipe", None) is not None:
        del app.state.pipe
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


app = FastAPI(title="AIGC Inpainting Backend", lifespan=lifespan)

# 配置 CORS：允许本地前端开发端口跨域访问 FastAPI 接口
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def health_check():
    # 提供基础健康检查接口，便于快速确认服务是否启动成功
    return {"status": "ok"}


@app.post("/api/redraw")
async def redraw(payload: RedrawRequest):
    try:
        if app.state.pipe is None:
            detail = getattr(app.state, "pipe_error", None) or "模型未就绪，请检查服务启动日志。"
            raise HTTPException(status_code=503, detail=f"模型未就绪：{detail}")

        if not payload.prompt.strip():
            raise HTTPException(status_code=400, detail="prompt 不能为空。")

        # 0) 将正向/反向提示词翻译为英文，提升模型对中文输入的兼容性
        english_prompt = translate_to_english(payload.prompt)
        english_negative_prompt = translate_to_english(payload.negative_prompt)
        print(f"prompt(原文): {payload.prompt}")
        print(f"prompt(英文): {english_prompt}")
        if payload.negative_prompt.strip():
            print(f"negative_prompt(原文): {payload.negative_prompt}")
            print(f"negative_prompt(英文): {english_negative_prompt}")

        # 1) 将前端 Base64 数据解码为 PIL 图像
        original_image = base64_to_pil(payload.original_image)
        mask_image = base64_to_pil(payload.mask_image)

        # 2) 使用同比例缩放+填充适配到 SDXL 输入，避免图像被强行拉伸
        original_image = resize_with_padding(
            image=original_image,
            target_size=1024,
            mode="RGB",
            background_color=(0, 0, 0),
            resample=Image.Resampling.LANCZOS,
        )
        # mask 使用最近邻缩放避免边缘灰阶插值，并保持黑底语义
        mask_image = resize_with_padding(
            image=mask_image,
            target_size=1024,
            mode="L",
            background_color=0,
            resample=Image.Resampling.NEAREST,
        )
        # 将 mask 强制二值化为 0/255 的硬边遮罩，提升局部重绘确定性
        mask_image = mask_image.point(lambda p: 255 if p > 127 else 0)

        # 3) 调用 Stable Diffusion Inpainting 进行局部重绘
        result = app.state.pipe(
            prompt=english_prompt,
            negative_prompt=english_negative_prompt,
            image=original_image,
            mask_image=mask_image,
            strength=payload.strength,
            num_inference_steps=35,
            guidance_scale=payload.guidance_scale,
        )
        result_image = result.images[0]

        # 4) 将结果图编码为 Base64 返回给前端
        result_image_base64 = pil_to_base64(result_image)

        return {
            "status": "success",
            "result_image": result_image_base64,
        }
    except HTTPException:
        raise
    except RuntimeError as exc:
        # 对显存不足等运行时异常给出清晰提示
        error_message = str(exc)
        if "out of memory" in error_message.lower():
            raise HTTPException(
                status_code=500,
                detail="GPU 显存不足（OOM），请降低分辨率/步数或释放显存后重试。",
            ) from exc
        raise HTTPException(status_code=500, detail=f"推理运行时错误: {error_message}") from exc
    except Exception as exc:
        # 统一兜底异常处理，保证接口出现异常时能返回明确错误信息
        raise HTTPException(status_code=500, detail=f"Inpainting 处理失败: {str(exc)}") from exc
