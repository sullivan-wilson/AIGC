import base64
import io
from contextlib import asynccontextmanager

import torch
from diffusers import StableDiffusionInpaintPipeline
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel


class RedrawRequest(BaseModel):
    prompt: str
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    在 FastAPI 启动阶段加载 Inpainting 模型，避免每次请求重复加载。
    优先使用 CUDA + float16，提高推理速度并降低显存占用。
    """
    try:
        model_id = "runwayml/stable-diffusion-inpainting"
        if not torch.cuda.is_available():
            raise RuntimeError("未检测到可用 CUDA GPU，当前仅配置了 GPU 推理。")

        app.state.pipe = StableDiffusionInpaintPipeline.from_pretrained(
            model_id,
            torch_dtype=torch.float16,
        )
        app.state.pipe = app.state.pipe.to("cuda")
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

        # 1) 将前端 Base64 数据解码为 PIL 图像
        original_image = base64_to_pil(payload.original_image)
        mask_image = base64_to_pil(payload.mask_image)

        # 2) 统一尺寸到模型推荐输入（512x512），避免尺寸不匹配导致推理报错
        original_image = original_image.resize((512, 512))
        # mask 要求黑白语义明显，转为 L 模式后再送入模型更稳妥
        mask_image = mask_image.convert("L").resize((512, 512))

        # 3) 调用 Stable Diffusion Inpainting 进行局部重绘
        result = app.state.pipe(
            prompt=payload.prompt,
            image=original_image,
            mask_image=mask_image,
            num_inference_steps=30,
            guidance_scale=7.5,
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
