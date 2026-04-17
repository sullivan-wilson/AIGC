<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { Canvas, FabricImage, Rect, StaticCanvas } from 'fabric'

const drawingCanvas = ref(null)
const fileInputRef = ref(null)
const promptText = ref('')
const negativePromptText = ref('green grass, vegetation, meadow, forest')
const strengthValue = ref(1.0)
const cfgScaleValue = ref(10.0)
const resultImageBase64 = ref('')
const isGenerating = ref(false)
let fabricCanvas = null
const CANVAS_SIZE = 600
const RECT_PREVIEW_OPACITY = 0.5

let isMouseDown = false
let startX = 0
let startY = 0
let activeRect = null

function bindRectangleDrawingEvents() {
  if (!fabricCanvas) {
    return
  }

  // 鼠标按下时创建一个半透明矩形，作为实时框选预览
  fabricCanvas.on('mouse:down', (event) => {
    const pointer = fabricCanvas.getPointer(event.e)
    isMouseDown = true
    startX = pointer.x
    startY = pointer.y

    activeRect = new Rect({
      left: startX,
      top: startY,
      width: 0,
      height: 0,
      fill: 'red',
      opacity: RECT_PREVIEW_OPACITY,
      selectable: false,
      evented: false
    })
    fabricCanvas.add(activeRect)
  })

  // 鼠标拖拽时更新矩形的左上角与宽高，支持任意方向拖拽
  fabricCanvas.on('mouse:move', (event) => {
    if (!isMouseDown || !activeRect) {
      return
    }

    const pointer = fabricCanvas.getPointer(event.e)
    const left = Math.min(startX, pointer.x)
    const top = Math.min(startY, pointer.y)
    const width = Math.abs(pointer.x - startX)
    const height = Math.abs(pointer.y - startY)

    activeRect.set({
      left,
      top,
      width,
      height
    })
    activeRect.setCoords()
    fabricCanvas.renderAll()
  })

  // 鼠标松开后结束当前框选；过小的误触矩形会被自动删除
  fabricCanvas.on('mouse:up', () => {
    isMouseDown = false
    if (activeRect) {
      const isTooSmall = activeRect.width < 2 || activeRect.height < 2
      if (isTooSmall) {
        fabricCanvas.remove(activeRect)
      }
    }
    activeRect = null
    fabricCanvas.renderAll()
  })
}

onMounted(() => {
  // 初始化 Fabric 画布，并限制在 600x600 的固定尺寸
  fabricCanvas = new Canvas(drawingCanvas.value, {
    width: CANVAS_SIZE,
    height: CANVAS_SIZE,
    isDrawingMode: false,
    selection: false
  })

  // 设置浅灰色背景，满足画板底色要求
  fabricCanvas.backgroundColor = '#e5e7eb'
  fabricCanvas.renderAll()

  // 绑定矩形框选交互：替代原来的自由画笔涂抹模式
  bindRectangleDrawingEvents()
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
    // 读取上传图片，用于设置为画布背景图（后续 original_image 会从画布坐标系导出）
    const dataUrl = await readFileAsDataURL(file)

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

function clearCanvas() {
  if (!fabricCanvas) {
    return
  }

  // 仅移除笔迹对象，保留背景色和绘图模式配置
  fabricCanvas.clear()
  fabricCanvas.backgroundColor = '#e5e7eb'
  fabricCanvas.isDrawingMode = false
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
        stroke: null,
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

async function buildOriginalImageBase64() {
  if (!fabricCanvas) {
    return ''
  }

  // original_image 从与遮罩同尺寸同坐标系的离屏画布导出，避免原图/遮罩错位
  const originalCanvas = new StaticCanvas(null, {
    width: CANVAS_SIZE,
    height: CANVAS_SIZE,
    backgroundColor: fabricCanvas.backgroundColor || '#e5e7eb'
  })

  try {
    if (fabricCanvas.backgroundImage) {
      const clonedBackground = await fabricCanvas.backgroundImage.clone()
      originalCanvas.backgroundImage = clonedBackground
    }
    originalCanvas.renderAll()
    return originalCanvas.toDataURL({ format: 'png' })
  } finally {
    originalCanvas.dispose()
  }
}

async function exportInpaintingData() {
  if (!fabricCanvas || isGenerating.value) {
    return
  }

  try {
    isGenerating.value = true
    const originalImageBase64 = await buildOriginalImageBase64()
    if (!originalImageBase64) {
      throw new Error('无法导出原图，请先上传底图。')
    }

    // 导出遮罩前临时把所有矩形设为不透明，导出后再恢复半透明预览
    const opacityBackup = []
    const objects = fabricCanvas.getObjects()
    objects.forEach((object) => {
      opacityBackup.push({ object, opacity: object.opacity })
      object.set({ opacity: 1 })
    })
    fabricCanvas.renderAll()

    let maskImageBase64 = ''
    try {
      maskImageBase64 = await buildMaskImageBase64()
    } finally {
      // 无论导出成功或失败，都恢复用户可见预览为半透明
      opacityBackup.forEach(({ object, opacity }) => {
        object.set({ opacity })
      })
      fabricCanvas.renderAll()
    }

    // 保留原有调试输出，便于前端快速确认导出内容是否正确
    console.log('original_image:', originalImageBase64)
    console.log('mask_image:', maskImageBase64)

    // 在控制台额外输出 prompt，方便联调时排查文本字段传输问题
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
    // 后端成功返回 result_image 后，直接用于页面展示
    if (!data?.result_image) {
      throw new Error('后端返回成功，但缺少 result_image 字段')
    }
    resultImageBase64.value = data.result_image
  } catch (error) {
    console.error('发送重绘数据失败：', error)
    alert('重绘失败，请检查网络连接或后端服务状态后重试。')
  } finally {
    isGenerating.value = false
  }
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
          <span class="text-sm text-slate-600">交互模式：拖拽绘制半透明矩形选区</span>
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
        </div>

        <div class="flex justify-center">
          <canvas
            ref="drawingCanvas"
            class="rounded border border-slate-300 shadow"
          />
        </div>

        <div class="mt-4 flex flex-wrap justify-center gap-3">
          <button
            class="rounded bg-red-500 px-4 py-2 text-white transition hover:bg-red-600"
            @click="clearCanvas"
          >
            清空
          </button>

          <button
            class="rounded bg-amber-500 px-4 py-2 text-white transition hover:bg-amber-600"
            @click="clearStrokesOnly"
          >
            只清空笔迹
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
