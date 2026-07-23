import { Router } from "express";
import { AuditController } from "../controllers/auditController";

const router = Router();

router.post("/audit", AuditController.runAudit);
router.get("/pages", AuditController.getPages);
router.get("/issues", AuditController.getIssues);
router.get("/architecture", AuditController.getArchitecture);
router.get("/history", AuditController.getHistory);
router.get("/page/:id", AuditController.getPageById);
router.get("/internal-links", AuditController.getInternalLinks);

export default router;
