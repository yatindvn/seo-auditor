import { AuditRequestParams } from "../types";
export declare function validateAuditRequest(input: any): {
    valid: boolean;
    error?: string;
    data?: AuditRequestParams;
};
