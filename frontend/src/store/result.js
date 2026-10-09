/** 分析结果（六大模块）缓存与导出。 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import { getResultByTask, downloadResult } from '@/api/result'

export const useResultStore = defineStore('result', () => {
  const cache = ref({}) // { [taskId]: result }
  const loadingTaskId = ref(null)
  const error = ref('')
  const exporting = ref('')

  const current = computed(() => (loadingTaskId.value ? cache.value[loadingTaskId.value] : null))

  async function load(taskId, { force = false } = {}) {
    if (!force && cache.value[taskId]) return cache.value[taskId]
    loadingTaskId.value = taskId
    error.value = ''
    try {
      const data = await getResultByTask(taskId)
      cache.value = { ...cache.value, [taskId]: data }
      return data
    } catch (err) {
      error.value = err?.status === 404 ? '该任务尚未生成分析结果' : err?.message || '结果加载失败'
      throw err
    } finally {
      loadingTaskId.value = null
    }
  }

  async function exportAs(result, format) {
    if (!result?.result_id) throw new Error('结果尚未就绪，无法导出')
    exporting.value = format
    try {
      return await downloadResult(result.result_id, format)
    } finally {
      exporting.value = ''
    }
  }

  function invalidate(taskId) {
    const next = { ...cache.value }
    delete next[taskId]
    cache.value = next
  }

  return { cache, loadingTaskId, error, exporting, current, load, exportAs, invalidate }
})
