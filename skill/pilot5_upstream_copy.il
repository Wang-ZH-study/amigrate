;; pilot5_upstream_copy.il — 在真实 OPA_D 的副本上：换器件 + 写尺寸
;; 关键：上游实例本身带 w/l/fingers/fw 属性，先验证 dbSet 在"真实实例"上是否生效
(printf "\n=== PILOT5 START\n")
(load "/tmp/abConvertComponentParams.il")
(load "/tmp/abInvokeCdfCallbacks.il")

(unless (ddGetObj "port_pilot")
  (ddCreateLib "port_pilot" "/home/IC/port_pilot"))
(when (ddGetObj "port_pilot" "OPA_D")
  (ddDeleteObj (ddGetObj "port_pilot" "OPA_D")))

(let (src dst changed)
  (setq src (dbOpenCellViewByType "weekfour_last" "OPA_D" "schematic" "schematic" "r"))
  (if (null src)
      (printf "ERROR: 打不开 weekfour_last/OPA_D\n")
      (progn
        (setq dst (dbCopyCellView src "port_pilot" "OPA_D" "schematic"))
        (dbClose src)
        (if (null dst)
            (printf "ERROR: 复制失败\n")
            (progn
              (dbClose dst)
              (setq dst (dbOpenCellViewByType "port_pilot" "OPA_D" "schematic" "schematic" "a"))
              (printf "copied: %d instances\n" (length dst~>instances))
              ;; 先看真实实例的存法
              (foreach i dst~>instances
                (when (equal i~>name "M1")
                  (printf "M1(before) master=%s/%s w=%L l=%L fingers=%L m=%L fw=%L\n"
                          i~>master~>libName i~>master~>cellName
                          i~>w i~>l i~>fingers i~>m i~>fw)))
              ;; 换器件
              (setq changed (abConvertComponentParams "/tmp/pilot_conv.config" dst))
              (printf "convert changed=%L\n" changed)
              ;; 写尺寸（硬编码）
              (foreach i dst~>instances
                (when (equal i~>name "M1")
                  (dbSet i "w" "9u")
                  (dbSet i "l" "500n")
                  (dbSet i "fingers" "2")
                  (dbSet i "m" "1")
                  (printf "M1(after) master=%s/%s w=%L l=%L fingers=%L m=%L\n"
                          i~>master~>libName i~>master~>cellName
                          i~>w i~>l i~>fingers i~>m)))
              (schCheck dst)
              (dbSave dst)
              (dbClose dst))))))

;; 重开验证
(let (cv i)
  (setq cv (dbOpenCellViewByType "port_pilot" "OPA_D" "schematic" "schematic" "r"))
  (foreach inst cv~>instances
    (when (equal inst~>name "M1")
      (printf "reopen M1: master=%s/%s w=%L l=%L fingers=%L m=%L\n"
              inst~>master~>libName inst~>master~>cellName
              inst~>w inst~>l inst~>fingers inst~>m)))
  (dbClose cv))

(printf "=== PILOT5 DONE\n")
(exit)