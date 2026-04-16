from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


class RedrawRequest(BaseModel):
    prompt: str
    original_image: str
    mask_image: str


app = FastAPI(title="AIGC Inpainting Backend")

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
        # 打印 prompt 和两张图片 Base64 长度，用于验证前后端传输链路完整
        print("prompt:", payload.prompt)
        print("original_image_length:", len(payload.original_image))
        print("mask_image_length:", len(payload.mask_image))

        return {
            "status": "success",
            "message": "后端已成功接收图片数据！",
        }
    except Exception as exc:
        # 统一兜底异常处理，保证接口出现异常时能返回明确错误信息
        raise HTTPException(status_code=500, detail=f"服务处理失败: {str(exc)}") from exc
