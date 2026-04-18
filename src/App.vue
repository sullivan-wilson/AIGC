<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { Canvas, Circle, FabricImage } from 'fabric'

const drawingCanvas = ref(null)
const fileInputRef = ref(null)
const promptText = ref('')
const negativePromptText = ref('green grass, vegetation, meadow, forest')
const strengthValue = ref(1.0)
const cfgScaleValue = ref(10.0)
const resultImageBase64 = ref('')
const isGenerating = ref(false)
const isSegmenting = ref(false)
const segmentStatusText = ref('')
const currentToolMode = ref('ai')
const brushSize = ref(24)
const eraserSize = ref(28)

let fabricCanvas = null
const CANVAS_SIZE = 600
const MASK_PREVIEW_OPACITY = 0.5

// 保存底图原始 Base64（原始分辨率），用于发送给 SAM 与 SDXL
const uploadedImageBase64 = ref('')

// 隐藏的离屏 Mask 累计层：内部始终使用“红色实心 + 透明背景”保存追加结果
let maskLayerCanvas = null
let maskLayerCtx = null

// 记录“底图在 600x600 画布中的映射关系”，用于把点击坐标反算到原图坐标
const imageMapping = {
  originalWidth: 0,
  originalHeight: 0,
  displayLeft: 0,
  displayTop: 0,
  displayWidth: 0,
  displayHeight: 0
}

let clickMarker = null
let maskOverlayImage = null
// 撤销栈：记录每次 SAM 追加前的离屏 mask 快照，实现“回退上一次点击”
const maskHistoryStack = []
let isManualDrawing = false
let lastDrawPoint = null
let overlayRenderScheduled = false
let overlayRenderToken = 0

const BRUSH_CURSOR = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 20 20'%3E%3Ccircle cx='8' cy='8' r='4' fill='%2322c55e' stroke='white' stroke-width='1.2'/%3E%3Cpath d='M11.5 11.5 L17 17' stroke='%230f172a' stroke-width='2' stroke-linecap='round'/%3E%3C/svg%3E") 2 2, crosshair`
const ERASER_CURSOR = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='22' height='22' viewBox='0 0 22 22'%3E%3Crect x='4' y='6' width='12' height='9' rx='2' ry='2' transform='rotate(-30 10 10)' fill='%23f97316' stroke='white' stroke-width='1.2'/%3E%3C/svg%3E") 3 3, cell`

onMounted(() => {
  // 初始化 Fabric 画布（不再使用画笔/矩形框选，只保留点击交互）
  fabricCanvas = new Canvas(drawingCanvas.value, {
    width: CANVAS_SIZE,
    height: CANVAS_SIZE,
    isDrawingMode: false,
    selection: false
  })

  // 设置浅灰色底色，便于观察图片留白区域
  fabricCanvas.backgroundColor = '#e5e7eb'
  fabricCanvas.renderAll()

  // 绑定“魔法点击”事件：点击图像后调用 SAM 分割
  bindMagicClickEvent()
  updateCanvasCursor()
})

function openUploadDialog() {
  fileInputRef.value?.click()
}

function readFileAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = () => reject(new Error('读取图片失败'))
    reader.readAsDataURL(file)
  })
}

function loadImageElement(dataUrl) {
  return new Promise((resolve, reject) => {
    const imageElement = new Image()
    imageElement.onload = () => resolve(imageElement)
    imageElement.onerror = () => reject(new Error('图片解码失败'))
    imageElement.src = dataUrl
  })
}

async function handleImageUpload(event) {
  const file = event.target.files?.[0]
  if (!file || !fabricCanvas) {
    return
  }

  try {
    const dataUrl = await readFileAsDataURL(file)
    uploadedImageBase64.value = dataUrl
    resetMaskLayer()
    removeMaskOverlay()
    removeClickMarker()

    // 重新加载底图并记录“原图尺寸 -> 画布展示尺寸”的映射关系
    const imageElement = await loadImageElement(dataUrl)
    imageMapping.originalWidth = imageElement.width
    imageMapping.originalHeight = imageElement.height

    const backgroundImage = new FabricImage(imageElement, {
      selectable: false,
      evented: false
    })

    const fitScale = Math.min(
      CANVAS_SIZE / imageElement.width,
      CANVAS_SIZE / imageElement.height
    )
    const fittedWidth = imageElement.width * fitScale
    const fittedHeight = imageElement.height * fitScale
    const left = (CANVAS_SIZE - fittedWidth) / 2
    const top = (CANVAS_SIZE - fittedHeight) / 2

    imageMapping.displayLeft = left
    imageMapping.displayTop = top
    imageMapping.displayWidth = fittedWidth
    imageMapping.displayHeight = fittedHeight
    initializeMaskLayer(imageElement.width, imageElement.height)

    backgroundImage.set({
      scaleX: fitScale,
      scaleY: fitScale,
      left,
      top
    })

    fabricCanvas.backgroundImage = backgroundImage
    fabricCanvas.renderAll()
  } catch (error) {
    console.error('上传底图失败：', error)
    alert('上传底图失败，请检查文件格式后重试。')
  } finally {
    event.target.value = ''
  }
}

function bindMagicClickEvent() {
  if (!fabricCanvas) {
    return
  }

  fabricCanvas.on('mouse:down', async (event) => {
    if (isSegmenting.value || isGenerating.value) {
      return
    }

    if (!uploadedImageBase64.value) {
      return
    }

    const pointer = fabricCanvas.getPointer(event.e)
    const mappedPoint = mapCanvasPointToOriginalImage(pointer.x, pointer.y, {
      roundToInteger: currentToolMode.value === 'ai'
    })
    if (!mappedPoint) {
      // 点击到留白区域时不触发分割，避免误操作
      return
    }

    if (currentToolMode.value === 'ai') {
      // 在点击位置画一个小圆点作为“魔法点击标记”
      renderClickMarker(pointer.x, pointer.y)
      // 调用 SAM：根据点击点智能生成贴边 mask
      await requestSamMask(mappedPoint.x, mappedPoint.y)
      return
    }

    // 画笔/橡皮擦模式：按下即开始在隐藏 mask 层手动绘制
    if (!maskLayerCanvas || !maskLayerCtx) {
      return
    }
    const snapshot = maskLayerCtx.getImageData(0, 0, maskLayerCanvas.width, maskLayerCanvas.height)
    maskHistoryStack.push(snapshot)
    isManualDrawing = true
    lastDrawPoint = mappedPoint
    drawOnMaskLayer(lastDrawPoint, mappedPoint)
    scheduleMaskOverlayRender()
  })

  fabricCanvas.on('mouse:move', (event) => {
    if (currentToolMode.value === 'ai' || !isManualDrawing || !lastDrawPoint) {
      return
    }
    const pointer = fabricCanvas.getPointer(event.e)
    const mappedPoint = mapCanvasPointToOriginalImage(pointer.x, pointer.y, { roundToInteger: false })
    if (!mappedPoint) {
      return
    }
    drawOnMaskLayer(lastDrawPoint, mappedPoint)
    lastDrawPoint = mappedPoint
    scheduleMaskOverlayRender()
  })

  fabricCanvas.on('mouse:up', finishManualDrawing)
  // 鼠标移出画布也要收笔，避免“无法继续画”的卡住状态
  fabricCanvas.on('mouse:out', finishManualDrawing)
}

function finishManualDrawing() {
  if (!isManualDrawing) {
    return
  }
  isManualDrawing = false
  lastDrawPoint = null
  scheduleMaskOverlayRender()
}

function drawOnMaskLayer(fromPoint, toPoint) {
  if (!maskLayerCtx) {
    return
  }

  maskLayerCtx.save()
  maskLayerCtx.lineCap = 'round'
  maskLayerCtx.lineJoin = 'round'
  const activeLineWidth = currentToolMode.value === 'eraser' ? Number(eraserSize.value) : Number(brushSize.value)
  maskLayerCtx.lineWidth = activeLineWidth

  if (currentToolMode.value === 'eraser') {
    // 橡皮擦：从隐藏 mask 层中扣除选区
    maskLayerCtx.globalCompositeOperation = 'destination-out'
    maskLayerCtx.strokeStyle = 'rgba(0, 0, 0, 1)'
  } else {
    // 画笔添加：往隐藏 mask 层追加纯红色不透明区域
    maskLayerCtx.globalCompositeOperation = 'source-over'
    maskLayerCtx.strokeStyle = 'rgba(255, 0, 0, 1)'
  }

  maskLayerCtx.beginPath()
  maskLayerCtx.moveTo(fromPoint.x, fromPoint.y)
  maskLayerCtx.lineTo(toPoint.x, toPoint.y)
  maskLayerCtx.stroke()
  maskLayerCtx.restore()
}

function mapCanvasPointToOriginalImage(canvasX, canvasY, options = { roundToInteger: true }) {
  const { displayLeft, displayTop, displayWidth, displayHeight, originalWidth, originalHeight } = imageMapping
  if (!displayWidth || !displayHeight || !originalWidth || !originalHeight) {
    return null
  }

  const insideX = canvasX >= displayLeft && canvasX <= displayLeft + displayWidth
  const insideY = canvasY >= displayTop && canvasY <= displayTop + displayHeight
  if (!insideX || !insideY) {
    return null
  }

  const normalizedX = (canvasX - displayLeft) / displayWidth
  const normalizedY = (canvasY - displayTop) / displayHeight
  const rawX = normalizedX * originalWidth
  const rawY = normalizedY * originalHeight
  const originalX = options.roundToInteger
    ? Math.max(0, Math.min(originalWidth - 1, Math.round(rawX)))
    : Math.max(0, Math.min(originalWidth - 1, rawX))
  const originalY = options.roundToInteger
    ? Math.max(0, Math.min(originalHeight - 1, Math.round(rawY)))
    : Math.max(0, Math.min(originalHeight - 1, rawY))
  return { x: originalX, y: originalY }
}

function renderClickMarker(canvasX, canvasY) {
  if (!fabricCanvas) {
    return
  }
  removeClickMarker()

  clickMarker = new Circle({
    left: canvasX - 3,
    top: canvasY - 3,
    radius: 3,
    fill: '#22c55e',
    stroke: '#ffffff',
    strokeWidth: 1,
    selectable: false,
    evented: false
  })
  fabricCanvas.add(clickMarker)
  fabricCanvas.renderAll()
}

function removeClickMarker() {
  if (fabricCanvas && clickMarker) {
    fabricCanvas.remove(clickMarker)
    clickMarker = null
  }
}

function removeMaskOverlay() {
  if (fabricCanvas && maskOverlayImage) {
    fabricCanvas.remove(maskOverlayImage)
    maskOverlayImage = null
  }
}

function setToolMode(mode) {
  currentToolMode.value = mode
  isManualDrawing = false
  lastDrawPoint = null
  updateCanvasCursor()
  if (mode !== 'ai') {
    // 进入手动模式时隐藏 AI 点击标记，避免视觉干扰
    removeClickMarker()
    fabricCanvas?.renderAll()
  }
}

function updateCanvasCursor() {
  if (!fabricCanvas) {
    return
  }
  if (currentToolMode.value === 'brush') {
    fabricCanvas.defaultCursor = BRUSH_CURSOR
  } else if (currentToolMode.value === 'eraser') {
    fabricCanvas.defaultCursor = ERASER_CURSOR
  } else {
    fabricCanvas.defaultCursor = 'crosshair'
  }
  fabricCanvas.renderAll()
}

async function requestSamMask(originalX, originalY) {
  if (!uploadedImageBase64.value || !fabricCanvas) {
    return
  }

  try {
    isSegmenting.value = true
    segmentStatusText.value = 'AI正在识别物体边缘...'

    const response = await fetch('http://127.0.0.1:8000/api/segment', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        image: uploadedImageBase64.value,
        points: [[originalX, originalY]]
      })
    })

    if (!response.ok) {
      throw new Error(`SAM 请求失败，状态码: ${response.status}`)
    }

    const data = await response.json()
    if (!data?.mask_image) {
      throw new Error('SAM 返回缺少 mask_image 字段')
    }

    // 追加模式：每次点击获取的新 mask 都叠加到隐藏离屏层，不清空旧结果
    await appendSamMaskToLayer(data.mask_image)
    await renderMaskOverlayFromLayer()
  } catch (error) {
    console.error('SAM 分割失败：', error)
    alert('智能抠图失败，请检查后端 /api/segment 服务是否正常。')
  } finally {
    isSegmenting.value = false
    segmentStatusText.value = ''
  }
}

function initializeMaskLayer(width, height) {
  maskLayerCanvas = document.createElement('canvas')
  maskLayerCanvas.width = width
  maskLayerCanvas.height = height
  maskLayerCtx = maskLayerCanvas.getContext('2d')
  maskLayerCtx.clearRect(0, 0, width, height)
  maskHistoryStack.length = 0
}

function resetMaskLayer() {
  if (!maskLayerCanvas || !maskLayerCtx) {
    return
  }
  maskLayerCtx.clearRect(0, 0, maskLayerCanvas.width, maskLayerCanvas.height)
  maskHistoryStack.length = 0
}

function hasMaskInLayer() {
  if (!maskLayerCanvas || !maskLayerCtx) {
    return false
  }
  const imageData = maskLayerCtx.getImageData(0, 0, maskLayerCanvas.width, maskLayerCanvas.height).data
  for (let i = 3; i < imageData.length; i += 4) {
    if (imageData[i] > 0) {
      return true
    }
  }
  return false
}

async function appendSamMaskToLayer(maskBase64) {
  if (!maskLayerCanvas || !maskLayerCtx) {
    throw new Error('Mask 累计层未初始化，请先上传底图。')
  }

  // 追加前先保存当前快照，供“撤销上一次点击”恢复
  const snapshot = maskLayerCtx.getImageData(0, 0, maskLayerCanvas.width, maskLayerCanvas.height)
  maskHistoryStack.push(snapshot)

  const maskImage = await loadImageElement(maskBase64)
  const tempCanvas = document.createElement('canvas')
  tempCanvas.width = maskLayerCanvas.width
  tempCanvas.height = maskLayerCanvas.height
  const tempCtx = tempCanvas.getContext('2d')
  tempCtx.drawImage(maskImage, 0, 0, tempCanvas.width, tempCanvas.height)

  // 把 SAM 返回黑白 mask 转为“红色实心 + 透明背景”，用于离屏层内部累计存储
  const imageData = tempCtx.getImageData(0, 0, tempCanvas.width, tempCanvas.height)
  for (let i = 0; i < imageData.data.length; i += 4) {
    const v = imageData.data[i]
    if (v > 127) {
      imageData.data[i] = 255
      imageData.data[i + 1] = 0
      imageData.data[i + 2] = 0
      imageData.data[i + 3] = 255
    } else {
      imageData.data[i + 3] = 0
    }
  }
  tempCtx.putImageData(imageData, 0, 0)

  // 追加叠加：source-over 写入隐藏层，重叠区域保持同一纯色，不会越来越深
  maskLayerCtx.globalCompositeOperation = 'source-over'
  maskLayerCtx.drawImage(tempCanvas, 0, 0)
}

async function undoLastSamClick() {
  if (!maskLayerCanvas || !maskLayerCtx) {
    return
  }
  if (maskHistoryStack.length === 0) {
    alert('当前没有可撤销的点击记录。')
    return
  }

  const previousSnapshot = maskHistoryStack.pop()
  maskLayerCtx.putImageData(previousSnapshot, 0, 0)
  scheduleMaskOverlayRender()
}

async function renderMaskOverlayFromLayer() {
  if (!fabricCanvas || !maskLayerCanvas) {
    return
  }
  removeMaskOverlay()
  if (!hasMaskInLayer()) {
    fabricCanvas.renderAll()
    return
  }

  const currentToken = ++overlayRenderToken
  // 统一透明度渲染：把“完整隐藏 Mask 层”作为单一图层显示，并设置整体 opacity=0.5
  const overlayDataUrl = maskLayerCanvas.toDataURL('image/png')
  const imageElement = await loadImageElement(overlayDataUrl)
  if (currentToken !== overlayRenderToken) {
    return
  }
  const overlay = new FabricImage(imageElement, {
    selectable: false,
    evented: false
  })
  const scaleX = imageMapping.displayWidth / imageElement.width
  const scaleY = imageMapping.displayHeight / imageElement.height
  overlay.set({
    left: imageMapping.displayLeft,
    top: imageMapping.displayTop,
    scaleX,
    scaleY,
    opacity: MASK_PREVIEW_OPACITY
  })

  maskOverlayImage = overlay
  fabricCanvas.add(maskOverlayImage)
  fabricCanvas.renderAll()
}

function scheduleMaskOverlayRender() {
  if (overlayRenderScheduled) {
    return
  }
  overlayRenderScheduled = true
  requestAnimationFrame(async () => {
    overlayRenderScheduled = false
    await renderMaskOverlayFromLayer()
  })
}

function buildMaskBase64ForRedraw() {
  if (!maskLayerCanvas || !maskLayerCtx || !hasMaskInLayer()) {
    return ''
  }

  // 导出给 /api/redraw 的终极 mask：黑底白前景，且白色区域 100% 不透明
  const exportCanvas = document.createElement('canvas')
  exportCanvas.width = maskLayerCanvas.width
  exportCanvas.height = maskLayerCanvas.height
  const exportCtx = exportCanvas.getContext('2d')
  exportCtx.fillStyle = '#000000'
  exportCtx.fillRect(0, 0, exportCanvas.width, exportCanvas.height)

  const sourceData = maskLayerCtx.getImageData(0, 0, maskLayerCanvas.width, maskLayerCanvas.height)
  const outputData = exportCtx.getImageData(0, 0, exportCanvas.width, exportCanvas.height)
  for (let i = 0; i < sourceData.data.length; i += 4) {
    const alpha = sourceData.data[i + 3]
    if (alpha > 0) {
      outputData.data[i] = 255
      outputData.data[i + 1] = 255
      outputData.data[i + 2] = 255
      outputData.data[i + 3] = 255
    } else {
      outputData.data[i] = 0
      outputData.data[i + 1] = 0
      outputData.data[i + 2] = 0
      outputData.data[i + 3] = 255
    }
  }
  exportCtx.putImageData(outputData, 0, 0)
  return exportCanvas.toDataURL('image/png')
}

function clearCanvas() {
  if (!fabricCanvas) {
    return
  }

  // 清空底图、SAM 遮罩与结果，回到初始状态
  fabricCanvas.clear()
  fabricCanvas.backgroundColor = '#e5e7eb'
  fabricCanvas.backgroundImage = null
  fabricCanvas.renderAll()

  uploadedImageBase64.value = ''
  resetMaskLayer()
  resultImageBase64.value = ''
  segmentStatusText.value = ''

  removeClickMarker()
  removeMaskOverlay()
  isManualDrawing = false
  lastDrawPoint = null
  imageMapping.originalWidth = 0
  imageMapping.originalHeight = 0
  imageMapping.displayLeft = 0
  imageMapping.displayTop = 0
  imageMapping.displayWidth = 0
  imageMapping.displayHeight = 0
  updateCanvasCursor()
}

function clearMaskOnly() {
  if (!fabricCanvas) {
    return
  }
  // 仅清空 SAM 遮罩与点击标记，保留底图便于重新点击选区
  resetMaskLayer()
  removeClickMarker()
  removeMaskOverlay()
  isManualDrawing = false
  lastDrawPoint = null
  fabricCanvas.renderAll()
}

async function exportInpaintingData() {
  if (!fabricCanvas || isGenerating.value) {
    return
  }

  try {
    if (!uploadedImageBase64.value) {
      throw new Error('请先上传底图。')
    }
    const maskImageBase64 = buildMaskBase64ForRedraw()
    if (!maskImageBase64) {
      throw new Error('请先点击图片，让 AI 识别并生成遮罩。')
    }

    isGenerating.value = true

    // 终极导出逻辑：发送后端 SAM 生成的二值 mask（语义上已是 100% 不透明）
    const originalImageBase64 = uploadedImageBase64.value
    console.log('original_image:', originalImageBase64)
    console.log('mask_image:', maskImageBase64)
    console.log('prompt:', promptText.value)
    console.log('negative_prompt:', negativePromptText.value)
    console.log('strength:', strengthValue.value)
    console.log('guidance_scale:', cfgScaleValue.value)

    const response = await fetch('http://127.0.0.1:8000/api/redraw', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        prompt: promptText.value,
        negative_prompt: negativePromptText.value,
        strength: Number(strengthValue.value),
        guidance_scale: Number(cfgScaleValue.value),
        original_image: originalImageBase64,
        mask_image: maskImageBase64
      })
    })

    if (!response.ok) {
      throw new Error(`请求失败，状态码: ${response.status}`)
    }

    const data = await response.json()
    if (!data?.result_image) {
      throw new Error('后端返回成功，但缺少 result_image 字段')
    }
    resultImageBase64.value = data.result_image
  } catch (error) {
    console.error('发送重绘数据失败：', error)
    alert(error?.message || '重绘失败，请检查网络连接或后端服务状态后重试。')
  } finally {
    isGenerating.value = false
  }
}

onUnmounted(() => {
  if (fabricCanvas) {
    // 组件销毁时释放 Fabric 资源，防止内存泄漏
    fabricCanvas.dispose()
    fabricCanvas = null
  }
})
</script>

<template>
  <main class="min-h-screen bg-slate-100 p-4">
    <div class="mx-auto grid max-w-[1320px] gap-4 lg:grid-cols-[720px_1fr]">
      <section class="rounded bg-white p-4 shadow">
        <h1 class="mb-4 text-lg font-semibold text-slate-800">AIGC 局部重绘工作台</h1>

        <div class="mb-4 flex flex-wrap items-center gap-4 rounded bg-slate-50 px-4 py-3">
          <input
            ref="fileInputRef"
            type="file"
            accept="image/*"
            class="hidden"
            @change="handleImageUpload"
          />

          <button
            class="rounded bg-sky-500 px-4 py-2 text-white transition hover:bg-sky-600"
            @click="openUploadDialog"
          >
            上传底图
          </button>
          <span class="text-sm text-slate-600">交互模式切换：</span>
          <button
            class="rounded px-3 py-1.5 text-sm text-white transition"
            :class="currentToolMode === 'ai' ? 'bg-sky-600' : 'bg-slate-500 hover:bg-slate-600'"
            @click="setToolMode('ai')"
          >
            AI 点选
          </button>
          <button
            class="rounded px-3 py-1.5 text-sm text-white transition"
            :class="currentToolMode === 'brush' ? 'bg-emerald-600' : 'bg-slate-500 hover:bg-slate-600'"
            @click="setToolMode('brush')"
          >
            画笔添加
          </button>
          <button
            class="rounded px-3 py-1.5 text-sm text-white transition"
            :class="currentToolMode === 'eraser' ? 'bg-rose-600' : 'bg-slate-500 hover:bg-slate-600'"
            @click="setToolMode('eraser')"
          >
            橡皮擦减去
          </button>
        </div>

        <div class="mb-4 rounded bg-slate-50 px-4 py-3">
          <label class="mb-2 block text-sm text-slate-700">重绘提示词（Prompt）</label>
          <input
            v-model="promptText"
            type="text"
            placeholder="例如：把被涂抹区域改成绿色草地"
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-sky-500"
          />

          <label class="mb-2 mt-3 block text-sm text-slate-700">反向提示词（Negative Prompt）</label>
          <input
            v-model="negativePromptText"
            type="text"
            placeholder="例如：green grass, vegetation, meadow, forest"
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-sky-500"
          />

          <label class="mb-2 mt-3 block text-sm text-slate-700">
            重绘强度（Strength）: {{ Number(strengthValue).toFixed(2) }}
          </label>
          <input
            v-model="strengthValue"
            type="range"
            min="0"
            max="1"
            step="0.01"
            class="w-full cursor-pointer"
          />

          <label class="mb-2 mt-3 block text-sm text-slate-700">
            提示词服从度（CFG Scale）: {{ Number(cfgScaleValue).toFixed(1) }}
          </label>
          <input
            v-model="cfgScaleValue"
            type="range"
            min="1"
            max="20"
            step="0.5"
            class="w-full cursor-pointer"
          />

          <label class="mb-2 mt-3 block text-sm text-slate-700">
            画笔粗细（仅画笔模式）: {{ brushSize }}
          </label>
          <input
            v-model="brushSize"
            type="range"
            min="2"
            max="80"
            step="1"
            class="w-full cursor-pointer"
          />

          <label class="mb-2 mt-3 block text-sm text-slate-700">
            橡皮擦粗细（仅橡皮擦模式）: {{ eraserSize }}
          </label>
          <input
            v-model="eraserSize"
            type="range"
            min="2"
            max="80"
            step="1"
            class="w-full cursor-pointer"
          />
        </div>

        <div class="flex justify-center">
          <canvas
            ref="drawingCanvas"
            class="rounded border border-slate-300 shadow"
          />
        </div>

        <p
          v-if="isSegmenting"
          class="mt-3 text-center text-sm text-sky-600"
        >
          {{ segmentStatusText || 'AI正在识别物体边缘...' }}
        </p>

        <div class="mt-4 flex flex-wrap justify-center gap-3">
          <button
            class="rounded bg-red-500 px-4 py-2 text-white transition hover:bg-red-600"
            @click="clearCanvas"
          >
            清空
          </button>

          <button
            class="rounded bg-amber-500 px-4 py-2 text-white transition hover:bg-amber-600"
            @click="clearMaskOnly"
          >
            清空当前遮罩
          </button>

          <button
            class="rounded bg-violet-500 px-4 py-2 text-white transition hover:bg-violet-600"
            @click="undoLastSamClick"
          >
            撤销上一次点击
          </button>

          <button
            class="rounded px-4 py-2 text-white transition disabled:cursor-not-allowed disabled:bg-slate-400"
            :class="isGenerating ? 'bg-slate-400' : 'bg-emerald-500 hover:bg-emerald-600'"
            :disabled="isGenerating"
            @click="exportInpaintingData"
          >
            {{ isGenerating ? 'AI 正在施展魔法...' : '获取重绘数据' }}
          </button>
        </div>
      </section>

      <section class="rounded bg-white p-4 shadow">
        <h2 class="mb-3 text-base font-semibold text-slate-800">重绘结果</h2>
        <div
          class="flex h-[640px] items-center justify-center overflow-hidden rounded border border-slate-300 bg-slate-50"
        >
          <img
            v-if="resultImageBase64"
            :src="resultImageBase64"
            alt="重绘结果图"
            class="max-h-full max-w-full object-contain"
          />
          <p
            v-else
            class="px-4 text-center text-sm text-slate-500"
          >
            结果图将在这里显示。请先上传底图、绘制遮罩并点击“获取重绘数据”。
          </p>
        </div>
      </section>
    </div>
  </main>
</template>
