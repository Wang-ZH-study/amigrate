;; pilot2_hardcoded.il — 不读 CSV，直接验证 dbSet w/l/fingers + CDF 回调能否写进 13mmrf/n12 实例
;; 用法：cd /home/IC && timeout 240 virtuoso -nograph < /tmp/pilot2_hardcoded.il

(printf "\n=== PILOT2 START\n")
(load "/tmp/abInvokeCdfCallbacks.il")

;; 建库（存在则复用）
(unless (ddGetObj "port_pilot")
  (ddCreateLib "port_pilot" "/home/IC/port_pilot"))

;; 清掉旧 cell，避免 panic 状态干扰
(when (ddGetObj "port_pilot" "pilot_n12")
  (ddDeleteObj (ddGetObj "port_pilot" "pilot_n12")))
(when (ddGetObj "port_pilot" "pilot_mos")
  (ddDeleteObj (ddGetObj "port_pilot" "pilot_mos")))

;; 1) 直接放一个 13mmrf/n12 实例
(let (cv inst)
  (setq cv (dbOpenCellViewByType "port_pilot" "pilot_n12" "schematic" "schematic" "w"))
  (if (null cv)
      (printf "ERROR: 建 cell 失败\n")
      (progn
        (setq inst (dbCreateInstByMasterName cv "smic13mmrf_1233" "n12" "symbol" "M1" 0:0 "R0"))
        (if (null inst)
            (printf "ERROR: 放 n12 实例失败\n")
            (progn
              (printf "created: master=%s/%s\n" inst~>master~>libName inst~>master~>cellName)
              (printf "before: w=%L l=%L fingers=%L m=%L\n"
                      inst~>w inst~>l inst~>fingers inst~>m)
              ;; 2) 硬编码写尺寸（字符串形式，避免 dbSet 类型错误）
              (dbSet inst "w" "2e-6")
              (dbSet inst "l" "0.5e-6")
              (dbSet inst "fingers" "1")
              (dbSet inst "m" "1")
              (printf "after dbSet: w=%L l=%L fingers=%L m=%L\n"
                      inst~>w inst~>l inst~>fingers inst~>m)
              ;; 3) 调 CDF 回调
              (abInvokeInstCdfCallbacks inst)
              (printf "after cdf: w=%L l=%L fingers=%L m=%L\n"
                      inst~>w inst~>l inst~>fingers inst~>m)
              (schCheck cv)
              (dbSave cv)
              (dbClose cv))))))

;; 4) 重新只读打开，验证是否落盘
(let (cv inst)
  (setq cv (dbOpenCellViewByType "port_pilot" "pilot_n12" "schematic" "schematic" "r"))
  (if (null cv)
      (printf "ERROR: 重新打开失败\n")
      (progn
        (setq inst (car cv~>instances))
        (printf "reopen: master=%s/%s w=%L l=%L fingers=%L m=%L\n"
                inst~>master~>libName inst~>master~>cellName
                inst~>w inst~>l inst~>fingers inst~>m)
        (dbClose cv))))

(printf "=== PILOT2 DONE\n")
(exit)