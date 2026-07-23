import { Router } from "express";
import { HealthController } from "../controllers/healthController";

const router = Router();

router.get("/health", HealthController.getHealth);

export default router;
