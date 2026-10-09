<script setup>
/** 附件模块：会话附件的上传、预览、下载与删除。 */
import { ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import EmptyState from '@/components/EmptyState.vue'
import { listAttachments, getAttachment, deleteAttachment, downloadAttachment } from '@/api/attachment'
import { parseStatusMeta } from '@/utils/constants'
import { formatBytes, formatDateTime } from '@/utils/format'

const props = defineProps({
  conversationId: { type: Number, default: null },
  // 由父组件在附件上传成功后 +1，触发刷新
  refreshKey: { type: Number, default: 0 },
})

const items = ref([])
const loading = ref(false)
const previewVisible = ref(false)
const previewText = ref('')
const previewTitle = ref('')

async function load() {
  if (!props.conversationId) {
    items.value = []
    return
  }
  loading.value = true
  try {
    const data = await listAttachments(props.conversationId)
    items.value = data.items || []
  } catch (err) {
    ElMessage.error(err?.message || '附件列表加载失败')
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.conversationId, props.refreshKey],
  () => load(),
  { immediate: true },
)

async function handlePreview(item) {
  try {
    const detail = await getAttachment(item.attachment_id)
    previewTitle.value = detail.file_name
    previewText.value = detail.preview || '（解析结果为空）'
    previewVisible.value = true
  } catch (err) {
    ElMessage.error(err?.message || '附件预览失败')
  }
}

async function handleDownload(item) {
  try {
    await downloadAttachment(item)
    ElMessage.success(`已开始下载 ${item.file_name}`)
  } catch (err) {
    ElMessage.error(err?.message || '附件下载失败')
  }
}

async function handleDelete(item) {
  try {
    await ElMessageBox.confirm(`确认删除附件「${item.file_name}」？文件将从磁盘一并移除。`, '删除附件', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteAttachment(item.attachment_id)
    ElMessage.success('附件已删除')
    load()
  } catch (err) {
    ElMessage.error(err?.message || '删除失败')
  }
}

defineExpose({ load })
</script>

<template>
  <section class="attach jy-card">
    <header class="head">
      <div class="head-left">
        <el-icon><FolderOpened /></el-icon>
        <span class="title">会话附件</span>
        <el-tag size="small" type="info" effect="plain" round>{{ items.length }}</el-tag>
      </div>
      <el-button size="small" text :loading="loading" @click="load">
        <el-icon><Refresh /></el-icon>
      </el-button>
    </header>

    <div v-loading="loading" class="body">
      <EmptyState
        v-if="!items.length && !loading"
        icon="Folder"
        title="暂无附件"
        description="在下方提问框里点「添加附件」上传 CSV / Excel / 文本，分析时会一并参考。"
      />
      <div v-for="item in items" :key="item.attachment_id" class="item">
        <el-icon class="item-icon"><Document /></el-icon>
        <div class="item-main">
          <div class="item-name" :title="item.file_name">{{ item.file_name }}</div>
          <div class="item-meta">
            <span>{{ item.file_type.toUpperCase() }}</span>
            <span>{{ formatBytes(item.file_size) }}</span>
            <span>{{ formatDateTime(item.created_at) }}</span>
          </div>
        </div>
        <el-tag
          size="small"
          effect="plain"
          :type="parseStatusMeta(item.parse_status, item.parse_status_text).type"
        >
          {{ parseStatusMeta(item.parse_status, item.parse_status_text).label }}
        </el-tag>
        <div class="item-actions">
          <el-button size="small" text @click="handlePreview(item)">预览</el-button>
          <el-button size="small" text @click="handleDownload(item)">下载</el-button>
          <el-button size="small" text type="danger" @click="handleDelete(item)">删除</el-button>
        </div>
      </div>
    </div>

    <el-dialog v-model="previewVisible" :title="previewTitle" width="640px">
      <pre class="preview jy-pre-wrap">{{ previewText }}</pre>
    </el-dialog>
  </section>
</template>

<style scoped>
.attach {
  padding: 14px 16px;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.head-left {
  display: flex;
  align-items: center;
  gap: 6px;
}

.head-left .title {
  font-size: 14px;
  font-weight: 600;
}

.head-left .el-icon {
  color: var(--jy-brand);
}

.body {
  margin-top: 10px;
  max-height: 320px;
  overflow-y: auto;
}

.item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid var(--jy-border-light);
}

.item:last-child {
  border-bottom: none;
}

.item-icon {
  color: var(--jy-text-placeholder);
}

.item-main {
  flex: 1;
  min-width: 0;
}

.item-name {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item-meta {
  display: flex;
  gap: 8px;
  font-size: 11px;
  color: var(--jy-text-placeholder);
  margin-top: 2px;
}

.item-actions {
  display: flex;
  gap: 0;
}

.preview {
  margin: 0;
  max-height: 420px;
  overflow: auto;
  font-size: 13px;
  line-height: 1.7;
  background: var(--jy-bg);
  padding: 12px;
  border-radius: var(--jy-radius-sm);
}
</style>
