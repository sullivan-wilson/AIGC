<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { Canvas, PencilBrush } from 'fabric'

const drawingCanvas = ref(null)
const brushColor = ref('#ef4444')
const brushWidth = ref(4)
let fabricCanvas = null

onMounted(() => {
  // 初始化 Fabric 画布，并限制在 600x600 的固定尺寸
  fabricCanvas = new Canvas(drawingCanvas.value, {
    width: 600,
    height: 600,
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
  </main>
</template>
