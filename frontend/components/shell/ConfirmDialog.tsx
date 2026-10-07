"use client";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

interface Props {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  busy?: boolean;
  onConfirm: () => void;
}

export default function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel, busy, onConfirm }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showCloseButton={false} className="float-layer">
        <DialogHeader>
          <DialogTitle className="text-base font-bold">{title}</DialogTitle>
          <DialogDescription className="text-sm text-fog">{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter className="!flex-row justify-end gap-2 border-0 bg-transparent p-0">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={onConfirm} disabled={busy}>
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
