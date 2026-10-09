<script setup>
/** 导出条：把一份分析结果导出为 md / json / xlsx。 */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import { useResultStore } from '@/store/result'
import { EXPORT_FORMATS } from '@/api/result'

const props = defineProps({
  result: { type: Object, required: true },
  size: { type: String, default: 'default' },
})

const results = useResultStore()
const busy = ref('')

async function handleExport(format) {
  busy.value = format
  try {
    const filename = await results.exportAs(props.result, format)
    ElMessage.success(`已开始下载：${filename}`)
  } catch (err) {
    ElMessage.error(err?.message || '导出失败')
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <div class="export-bar">
    <span class="label">导出</span>
    <el-button
      v-for="fmt in EXPORT_FORMATS"
      :key="fmt.value"
      :size="size"
      :loading="busy === fmt.value"
      :disabled="!result?.result_id"
      @click="handleExport(fmt.value)"
    >
      <el-icon v-if="fmt.value === 'md'"><Document /></el-icon>
      <el-icon v-else-if="fmt.value === 'json'"><Tickets /></el-icon>
      <el-icon v-else><Grid /></el-icon>
      {{ fmt.label }}
    </el-button>
  </div>
</template>

<style scoped>
.export-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.label {
  font-size: 13px;
  color: var(--jy-text-secondary);
  margin-right: 2px;
}
</style>
