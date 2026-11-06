import { WORKSPACE_LABELS } from '../../lib/format'
import type { Workspace } from '../../lib/types'
import { btnSecondary } from '../ui/buttons'
import { Modal } from '../ui/Modal'
import { SwitchWorkspaceForm } from './SwitchWorkspaceForm'

export function SwitchWorkspaceModal({ target, onClose }: { target: Workspace; onClose: () => void }) {
  return (
    <Modal
      title={`Switch to ${WORKSPACE_LABELS[target]}`}
      description="For your security, enter your password to open the other workspace."
      onClose={onClose}
    >
      <SwitchWorkspaceForm
        target={target}
        footer={
          <button type="button" onClick={onClose} className={`${btnSecondary} border-line`}>
            Cancel
          </button>
        }
      />
    </Modal>
  )
}
