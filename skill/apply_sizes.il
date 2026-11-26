/* abApplySizes.il — 把 sizing_table.csv 的尺寸写回目标库原理图
 *
 * 配合 abConvertComponentParams.il：
 *   1) dbCopyCellView 把源库复制成目标库；
 *   2) conv.config 换器件 master；
 *   3) 本脚本按实例名写 w/l/nf/m。
 *
 * 用法：
 *   load("apply_sizes.il")
 *   abApplySizes("sizing_table.csv" ?cellView cv ?dryRun t)
 *   abApplySizes("sizing_table.csv" ?cellView cv
 *                ?paramMap (list (list "w" "w") (list "l" "l")
 *                                (list "nf" "fingers") (list "m" "m")))
 *
 * CSV 列（顺序固定，首行表头）：inst,dev_src,dev_tgt,L_um,W_um,nf,m,vsb,vds,vgs,note
 * W_um 是总宽；写进 CDF 的单指宽 w = W_um / (nf*m) * 1e-6。
 *
 * 硬边界：不重连引脚；只写尺寸不判好坏；找不到实例/参数要报错不静默。
 */

(procedure (abApplySizesSizeToFinger wTotalUm nf m)
  (quotient wTotalUm (max 1 (times nf m))))

(procedure (abApplySizesReadCsv csvFile)
  (let (prt line fields out)
    (setq out nil)
    (when (setq prt (infile csvFile))
      (gets prt)                       ; 跳过表头
      (while (setq line (gets prt))
        (when (and line (neq line ""))
          (setq fields (parseString line ","))
          (when (and fields (car fields) (neq (car fields) ""))
            (setq out (cons fields out)))))
      (close prt))
    (reverse out)))

(procedure (abApplySizesSetParam inst paramName value dryRun)
  (if dryRun
      (printf "  [dry] %s.%s = %L\n" inst~>name paramName value)
      (dbReplaceProp inst paramName 'string value)))

(procedure (abApplySizes csvFile @key cellView dryRun paramMap)
  (let (rows failed)
    (when (null cellView) (setq cellView (geGetEditCellView)))
    (when (null paramMap)
      (setq paramMap (list (list "w" "w") (list "l" "l")
                           (list "nf" "nf") (list "m" "m"))))
    (setq rows (abApplySizesReadCsv csvFile))
    (if (null rows)
        (progn
          (printf "ERROR: %s 没有数据行\n" csvFile)
          nil)
        (progn
          (setq failed nil)
          (foreach row rows
            (let (name lUm wTotal nf m found wFinger)
              (setq name   (nth 0 row))
              (setq lUm    (atof (nth 3 row)))
              (setq wTotal (atof (nth 4 row)))
              (setq nf     (max 1 (atoi (nth 5 row))))
              (setq m      (max 1 (atoi (nth 6 row))))
              (setq found nil)
              (foreach inst cellView~>instances
                (when (equal inst~>name name) (setq found inst)))
              (if (null found)
                  (progn
                    (printf "ERROR: 实例 %s 不在当前 cellView\n" name)
                    (setq failed (cons name failed)))
                  (progn
                    (setq wFinger (abApplySizesSizeToFinger wTotal nf m))
                    (printf "apply %s: L=%.3fum W_total=%.3fum nf=%d m=%d -> w=%.3fum\n"
                            name lUm wTotal nf m wFinger)
                    (abApplySizesSetParam found (cadr (assoc "l" paramMap)) (sprintf nil "%gu" lUm) dryRun)
                    (abApplySizesSetParam found (cadr (assoc "w" paramMap)) (sprintf nil "%gu" wFinger) dryRun)
                    (abApplySizesSetParam found (cadr (assoc "nf" paramMap)) (sprintf nil "%d" nf) dryRun)
                    (abApplySizesSetParam found (cadr (assoc "m" paramMap)) (sprintf nil "%d" m) dryRun)
                    (when (null dryRun) (abInvokeInstCdfCallbacks found))))))
          (when (null dryRun)
            (schCheck cellView)
            (dbSave cellView))
          (when failed
            (printf "WARNING: %d 个实例未写入：%L\n" (length failed) failed))
          (null failed)))))