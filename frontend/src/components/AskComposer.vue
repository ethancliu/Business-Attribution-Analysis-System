<script setup>
/** 提问输入区：文本 + 待发送附件 + 推荐问题。 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { uploadAttachment, deleteAttachment } from '@/api/attachment'
import { formatBytes } from '@/utils/format'
import { DEMO_QUESTIONS } from '@/utils/constants'
import { useUserStore } from '@/store/user'

const props = defineProps({
  conversationId: { type: Number, default: null },
  disabled: { type: Boolean, default: false },
  sending: { type: Boolean, default: false },
  analyzing: { type: Boolean, default: false },
})

const emit = defineEmits(['send', 'cancel', 'uploaded'])

const user = useUserStore()

const content = ref('')
const pending = ref([]) // 已上传、待随本轮提问一起发送的附件
const uploading = ref(false)
const fileInput = ref(null)

const maxMb = computed(() => user.publicConfig?.upload_max_mb ?? 50)
const allowedExt = computed(
  () => user.publicConfig?.allowed_upload_ext ?? ['txt', 'md', 'csv', 'json', 'xlsx', 'xls', 'pdf', 'log'],
)
const acceptAttr = computed(() => allowedExt.value.map((e) => `.${e}`).join(','))
const canSend = computed(() => !!props.conversationId && content.value.trim().length > 0 && !props.disabled)

function triggerPick() {
  if (!props.conversationId) {
    ElMessage.warning('请先选择或新建一个会话')
    return
  }
  fileInput.value?.click()
}

function validate(file) {
  const ext = (file.name.split('.').pop() || '').toLowerCase()
  if (!allowedExt.value.includes(ext)) {
    ElMessage.error(`不支持的附件类型 .${ext}，允许：${allowedExt.value.join(' / ')}`)
    return false
  }
  if (file.size > maxMb.value * 1024 * 1024) {
    ElMessage.error(`附件超过 ${maxMb.value} MB 上限`)
    return false
  }
  return true
}

async function onFilesPicked(event) {
  const files = Array.from(event.target.files || [])
  event.target.value = ''
  if (!files.length) return

  uploading.value = true
  try {
    for (const file of files) {
      if (!validate(file)) continue
      const res = await uploadAttachment(props.conversationId, file)
      pending.value.push({
        attachment_id: res.attachment_id,
        file_name: res.file_name,
        file_size: res.file_size,
        parse_status: res.parse_status,
      })
      ElMessage.success(`已上传 ${res.file_name}`)
      emit('uploaded', res)
    }
  } catch (err) {
    ElMessage.error(err?.message || '附件上传失败')
  } finally {
    uploading.value = false
  }
}

async function removePending(item) {
  pending.value = pending.value.filter((a) => a.attachment_id !== item.attachment_id)
  try {
    await deleteAttachment(item.attachment_id)
  } catch {
    // 删除失败不影响本轮提问，附件仍会出现在会话附件列表里
  }
  emit('uploaded', null)
}

function handleSend() {
  if (!canSend.value) return
  const ids = pending.value.map((a) => a.attachment_id)
  emit('send', { content: content.value.trim(), attachmentIds: ids })
  content.value = ''
  pending.value = []
}

function useDemo(question) {
  content.value = question
}

function onKeydown(event) {
  // Enter 发送，Shift+Enter 换行
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    handleSend()
  }
}
</script>

<template>
  <div class="composer">
    <div v-if="!conversationId" class="hint">
      <el-icon><InfoFilled /></el-icon>
      请先在左侧选择或新建一个会话，再开始提问。
    </div>

    <template v-else>
      <div class="suggest" v-if="!disabled">
        <span class="suggest-label">试试这样问：</span>
        <el-tag
          v-for="q in DEMO_QUESTIONS.slice(0, 3)"
          :key="q"
          class="suggest-tag"
          size="small"
          effect="plain"
          @click="useDemo(q)"
        >
          {{ q }}
        </el-tag>
      </div>

      <div v-if="pending.length" class="pending">
        <el-tag
          v-for="item in pending"
          :key="item.attachment_id"
          closable
          type="info"
          effect="plain"
          @close="removePending(item)"
        >
          <el-icon><Paperclip /></el-icon>
          {{ item.file_name }}（{{ formatBytes(item.file_size) }}）
        </el-tag>
      </div>

      <div class="input-row">
        <el-input
          v-model="content"
          type="textarea"
          :rows="3"
          resize="none"
          maxlength="4000"
          show-word-limit
          :disabled="disabled"
          placeholder="描述你想归因的经营问题，例如：信息流渠道 ROAS 从 5.9 掉到 1.6，投放预算没变，问题出在哪？（Enter 发送，Shift+Enter 换行）"
          @keydown="onKeydown"
        />

        <div class="actions">
          <div class="actions-left">
            <el-button :disabled="disabled || uploading" :loading="uploading" @click="triggerPick">
              <el-icon><Paperclip /></el-icon>
              添加附件
            </el-button>
            <span class="limit jy-muted">
              支持 {{ allowedExt.join(' / ') }}，单个不超过 {{ maxMb }} MB
            </span>
          </div>
          <div class="actions-right">
            <el-button v-if="analyzing" type="danger" plain @click="emit('cancel')">
              取消分析
            </el-button>
            <el-button type="primary" :disabled="!canSend" :loading="sending" @click="handleSend">
              <el-icon><Promotion /></el-icon>
              发送并分析
            </el-button>
          </div>
        </div>
      </div>
    </template>

    <input
      ref="fileInput"
      class="file-input"
      type="file"
      multiple
      :accept="acceptAttr"
      @change="onFilesPicked"
    />
  </div>
</template>

<style scoped>
.composer {
  border-top: 1px solid var(--jy-border);
  background: var(--jy-bg-card);
  padding: 12px 20px 16px;
}

.file-input {
  display: none;
}

.hint {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--jy-text-secondary);
  font-size: 13px;
  padding: 10px 0;
}

.suggest {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.suggest-label {
  font-size: 12px;
  color: var(--jy-text-placeholder);
}

.suggest-tag {
  cursor: pointer;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.suggest-tag:hover {
  color: var(--jy-brand);
  border-color: var(--jy-brand);
}

.pending {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 10px;
}

.actions-left,
.actions-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.limit {
  font-size: 12px;
}
</style>
