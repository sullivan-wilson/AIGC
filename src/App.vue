<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { Canvas, FabricImage, PencilBrush, StaticCanvas } from 'fabric'

const drawingCanvas = ref(null)
const fileInputRef = ref(null)
const brushColor = ref('#ef4444')
const brushWidth = ref(4)
const originalImageBase64 = ref('')
let fabricCanvas = null
const CANVAS_SIZE = 600

onMounted(() => {
  // 初始化 Fabric 画布，并限制在 600x600 的固定尺寸
  fabricCanvas = new Canvas(drawingCanvas.value, {
    width: CANVAS_SIZE,
    height: CANVAS_SIZE,
    isDrawingMode: true
  })

  // 设置浅灰色背景，满足画板底色要求
  fabricCanvas.backgroundColor = '#e5e7eb'
  fabricCanvas.renderAll()

  // 配置自由画笔：将颜色和粗细都绑定到响应式变量，便于后续通过 UI 实时调节
  const brush = new PencilBrush(fabricCanvas)
  brush.color = brushColor.value
  brush.width = brushWidth.value
  fabricCanvas.freeDrawingBrush = brush
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
    // 保留原图 Base64，用于后续点击“获取重绘数据”时直接输出 original_image
    const dataUrl = await readFileAsDataURL(file)
    originalImageBase64.value = dataUrl

    // 使用原生 Image 获取真实宽高，再交给 FabricImage，便于精确计算缩放比例
    const imageElement = await loadImageElement(dataUrl)
    const backgroundImage = new FabricImage(imageElement, {
      selectable: false,
      evented: false
    })

    // 等比缩放：以“完全容纳在 600x600 画布内”为目标，防止拉伸变形和超出边界
    const fitScale = Math.min(
      CANVAS_SIZE / imageElement.width,
      CANVAS_SIZE / imageElement.height
    )
    const fittedWidth = imageElement.width * fitScale
    const fittedHeight = imageElement.height * fitScale
    backgroundImage.set({
      scaleX: fitScale,
      scaleY: fitScale,
      left: (CANVAS_SIZE - fittedWidth) / 2,
      top: (CANVAS_SIZE - fittedHeight) / 2
    })

    // 设置为 Fabric 画布背景图：笔迹仍然绘制在背景图之上
    fabricCanvas.backgroundImage = backgroundImage
    fabricCanvas.renderAll()
  } catch (error) {
    console.error('上传底图失败：', error)
  } finally {
    // 清空 input 值，允许用户重复选择同一张图片时仍可触发 change 事件
    event.target.value = ''
  }
}

function updateBrushColor() {
  if (!fabricCanvas?.freeDrawingBrush) {
    return
  }

  // 每次颜色选择器变化时，都同步更新 Fabric 当前画笔颜色
  fabricCanvas.freeDrawingBrush.color = brushColor.value
}

function updateBrushWidth() {
  if (!fabricCanvas?.freeDrawingBrush) {
    return
  }

  // 每次滑动条变化时，都同步更新 Fabric 当前画笔粗细
  fabricCanvas.freeDrawingBrush.width = Number(brushWidth.value)
}

function clearCanvas() {
  if (!fabricCanvas) {
    return
  }

  // 仅移除笔迹对象，保留背景色和绘图模式配置
  fabricCanvas.clear()
  fabricCanvas.backgroundColor = '#e5e7eb'
  fabricCanvas.isDrawingMode = true
  // 清空后再次确保画笔参数与当前 UI 状态一致，避免出现样式不同步
  updateBrushColor()
  updateBrushWidth()
  fabricCanvas.renderAll()
}

function clearStrokesOnly() {
  if (!fabricCanvas) {
    return
  }

  // 仅清理绘制对象，保留 backgroundImage（底图）和画布当前背景色
  const objects = fabricCanvas.getObjects()
  objects.forEach((object) => fabricCanvas.remove(object))
  fabricCanvas.renderAll()
}

async function buildMaskImageBase64() {
  if (!fabricCanvas) {
    return ''
  }

  // 新建离屏 StaticCanvas 专门用于生成遮罩图，避免污染用户当前画板
  const maskCanvas = new StaticCanvas(null, {
    width: CANVAS_SIZE,
    height: CANVAS_SIZE,
    backgroundColor: '#000000'
  })

  try {
    // 遍历用户笔迹对象并克隆到离屏画布，统一改成纯白，保证输出为标准黑白遮罩
    const objects = fabricCanvas.getObjects()
    for (const object of objects) {
      const clonedObject = await object.clone()
      clonedObject.set({
        fill: '#ffffff',
        stroke: '#ffffff',
        opacity: 1,
        shadow: null
      })
      maskCanvas.add(clonedObject)
    }

    maskCanvas.renderAll()
    return maskCanvas.toDataURL({ format: 'png' })
  } finally {
    // 遮罩导出完成后立即销毁离屏画布，防止额外内存占用
    maskCanvas.dispose()
  }
}

async function exportInpaintingData() {
  if (!fabricCanvas) {
    return
  }

  const maskImageBase64 = await buildMaskImageBase64()
  console.log('original_image:', originalImageBase64.value)
  console.log('mask_image:', maskImageBase64)
}

onUnmounted(() => {
  if (fabricCanvas) {
    // 组件销毁时释放 Fabric 相关资源，避免内存泄漏
    fabricCanvas.dispose()
    fabricCanvas = null
  }
})
</script>

<template>
  <main class="flex min-h-screen flex-col items-center justify-center bg-slate-100 p-4">
    <div class="mb-4 flex items-center gap-4 rounded bg-white px-4 py-3 shadow">
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

      <label class="flex items-center gap-2 text-sm text-slate-700">
        画笔颜色
        <input
          v-model="brushColor"
          type="color"
          class="h-8 w-10 cursor-pointer rounded border border-slate-300 bg-white p-0"
          @input="updateBrushColor"
        />
      </label>

      <label class="flex items-center gap-2 text-sm text-slate-700">
        画笔粗细
        <input
          v-model="brushWidth"
          type="range"
          min="1"
          max="30"
          class="w-40 cursor-pointer"
          @input="updateBrushWidth"
        />
        <span class="w-8 text-right">{{ brushWidth }}</span>
      </label>
    </div>

    <canvas
      ref="drawingCanvas"
      class="rounded border border-slate-300 shadow"
    />

    <button
      class="mt-4 rounded bg-red-500 px-4 py-2 text-white transition hover:bg-red-600"
      @click="clearCanvas"
    >
      清空
    </button>

    <button
      class="mt-3 rounded bg-amber-500 px-4 py-2 text-white transition hover:bg-amber-600"
      @click="clearStrokesOnly"
    >
      只清空笔迹
    </button>

    <button
      class="mt-3 rounded bg-emerald-500 px-4 py-2 text-white transition hover:bg-emerald-600"
      @click="exportInpaintingData"
    >
      获取重绘数据
    </button>
  </main>
</template>
